# Urgency scoring

The scorer answers one question per node: how likely is this to need a human's attention soon, and how bad if it does. It runs continuously in the background over changed subgraphs, not on demand, so a high score exists before anyone asks. Output is a score in [0, 1], the feature vector that produced it, and a confidence derived from the provenance of the underlying edges.

The design is deliberately a transparent weighted model first, with an optional learned (GNN) scorer layered on top later. A weighted model is explainable by construction — the notification can say which features drove the score — and needs no labeled training data to start. The learned scorer is an enhancement, not a dependency (see the end of this doc and [ADR-0010](../adr/0010-gnn-urgency-scorer.md)).

---

## Features

Features fall into three groups: intrinsic (properties of the node), relational (properties of its neighborhood in the graph), and temporal (time pressure). Each is normalized to [0, 1].

Intrinsic:

| Feature | Signal | Normalization |
|---|---|---|
| `incident_severity` | PagerDuty SEV of a linked/own incident | SEV1=1.0, SEV2=0.7, SEV3=0.4, SEV4=0.2 |
| `service_criticality` | tier of the affected service | tier0=1.0 … tier3=0.25 |
| `repo_importance` | repo weight (deploy frequency, dependents) | min-max across org |
| `ticket_priority` | Jira priority | Blocker=1.0 … Low=0.2 |

Relational (computed over the k-hop subgraph):

| Feature | Signal |
|---|---|
| `blocked_dependency_count` | count of open `BLOCKS` edges upstream of a pending deployment |
| `blast_radius` | number of services reachable via `CALLS`/`DEPENDS_ON` from the affected node |
| `owner_workload` | open high-urgency items already assigned to the owner (penalizes piling on) |
| `discussion_velocity` | rate of Slack messages in threads that `DISCUSSES` this entity, last hour vs baseline |
| `recent_incident_density` | incidents on this service in trailing 7 days |
| `cross_source_corroboration` | how many distinct sources independently reference this entity (a thing seen in GitHub + Jira + PagerDuty is realer than one seen once) |

Temporal:

| Feature | Signal |
|---|---|
| `deployment_proximity` | closeness of a scheduled deployment that this node blocks (sooner = higher) |
| `meeting_proximity` | closeness of a meeting that `DISCUSSES` this node (drives meeting-prep surfacing) |
| `ticket_age` | age vs. team's normal cycle time (staleness) |
| `incident_age` | how long an open incident has been unresolved |
| `freshness` | recency of the last event touching the node (decays; stale nodes fade) |

---

## Scoring formula

The base score is a weighted sum passed through a logistic squash so no single feature saturates the result, combined multiplicatively with a decay so that stale nodes fall regardless of past weight.

```
raw       = Σ_i  w_i · f_i                      # weighted feature sum
base      = sigmoid(k · (raw − b))              # squash; k steepness, b bias
decay     = exp(−λ · hours_since_last_event)    # temporal decay
urgency   = base · decay
```

Weights `w_i` are configured per org (defaults below) and are the model's tunable surface. `k` and `b` calibrate the operating point (how eager the system is); `λ` sets how fast unattended items fade.

Default weights (sum need not be 1; the squash handles scale):

```yaml
weights:
  incident_severity:        0.95
  blocked_dependency_count: 0.85
  deployment_proximity:     0.80
  service_criticality:      0.75
  blast_radius:             0.70
  ticket_priority:          0.55
  discussion_velocity:      0.50
  cross_source_corroboration: 0.50
  recent_incident_density:  0.45
  repo_importance:          0.40
  incident_age:             0.40
  meeting_proximity:        0.35
  ticket_age:               0.30
  owner_workload:          -0.30   # negative: dampens piling onto a loaded owner
calibration:
  k: 6.0
  b: 0.45
decay:
  lambda: 0.02        # per hour; ~35h half-life
thresholds:
  reason_at:   0.60   # above this, run LLM reasoning
  interrupt_at: 0.75  # above this, may interrupt a human (else digest)
```

The motivating example scores high because several top-weighted features fire at once: an open SEV-2 (`incident_severity`), a blocked dependency on a near-term deploy (`blocked_dependency_count` × `deployment_proximity`), a tier-0 service (`service_criticality`), and three sources corroborating (`cross_source_corroboration`). Any one alone would likely sit below `reason_at`; the graph is what lets them compound.

---

## Confidence

Score and confidence are separate. The score says how urgent; confidence says how much to trust the score given the evidence. Confidence is the aggregate confidence of the edges the score rests on:

```
confidence = min(edge_confidence for edge in evidence_path)
```

An urgency driven by deterministic edges (GitHub author, PagerDuty severity) carries high confidence. The same urgency driven partly by an LLM-inferred `DEPENDS_ON` carries lower confidence, and the notification says so. This keeps the system honest: it will surface a plausible-but-uncertain risk, labeled as such, rather than either hiding it or overselling it.

---

## Background execution

Scoring is a Ray job triggered by `graph.changes`. It never scans the whole graph:

1. Coalesce a burst of change events into one changed-node set (debounce window ~1s).
2. For each changed node, pull the k-hop subgraph (default k=2) from Neo4j.
3. Fan the subgraphs across Ray workers; each computes the feature vector and score.
4. Write the score back onto the node (`urgency`, `urgency_features`, `scored_at`).
5. For nodes crossing `reason_at`, emit `risk.scored` to trigger the LLM stage.

Cost is proportional to churn, not to graph size, so freshness holds as the graph grows past 100k nodes. Re-scoring the same node within a short window is cached in Redis keyed by the subgraph's content hash, so a node touched repeatedly in a burst is scored once.

---

## Optional learned scorer

The weighted model is the default and the fallback. A graph neural network (GraphSAGE-style, on the k-hop subgraph) can be trained later on outcome labels — did this node actually lead to a page, a rollback, a missed deadline — to predict urgency directly, capturing feature interactions the linear model misses. It runs as a Modal GPU worker and returns a score plus attention weights that map back to nodes for explainability. It is gated behind a config flag and only used where a trained model exists for the org; everywhere else the weighted model runs. Trade-offs and the labeling scheme are in [ADR-0010](../adr/0010-gnn-urgency-scorer.md). Nothing in the pipeline depends on it being present.
