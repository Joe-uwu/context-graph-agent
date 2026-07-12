# Sequence diagrams

Four runtime flows: event ingestion into a graph update, the proactive notification path, a hybrid retrieval query, and the LLM reasoning/grounding step. All are Mermaid `sequenceDiagram`.

---

## 1. Event ingestion → graph update

A PR is merged in GitHub. Cortex turns that into typed entities, resolves them against existing nodes, discovers relationships, and writes the delta.

```mermaid
sequenceDiagram
    autonumber
    participant GH as GitHub
    participant ING as ingestion-service
    participant K as Kafka
    participant ENT as entity-service
    participant GR as graph-service
    participant NEO as Neo4j

    GH->>ING: webhook: pull_request.closed (merged)
    ING->>ING: dedupe (delivery id), rate-limit, normalize
    ING->>K: produce raw.events {source: github, type: pr_merged}
    K->>ENT: consume raw.events
    ENT->>ENT: deterministic extract (PR, author, repo, refs)
    ENT->>ENT: LLM extract (services touched, intent) — structured output
    ENT->>K: produce entities.extracted
    K->>GR: consume entities.extracted
    GR->>NEO: resolve entities (MERGE person/repo/PR by natural key)
    GR->>GR: relationship discovery (rules → embedding → LLM residue)
    GR->>NEO: MERGE edges (AUTHORED, REFERENCES, TOUCHES) with provenance+confidence
    GR->>K: produce graph.changes {changed_node_ids:[...]}
    Note over GR,K: offset committed only after produce — at-least-once, idempotent MERGE makes replay safe
```

---

## 2. Proactive notification path

`graph.changes` triggers scoring; a threshold crossing triggers reasoning; the notification engine decides whether it is worth interrupting someone.

```mermaid
sequenceDiagram
    autonumber
    participant K as Kafka
    participant RANK as ranking-service (Ray)
    participant NEO as Neo4j
    participant LLM as llm-service (LangGraph)
    participant RET as retrieval-service
    participant NOTIF as notification-service
    participant CH as Slack / Email / Dashboard

    K->>RANK: consume graph.changes {changed_node_ids}
    RANK->>RANK: debounce/coalesce burst → changed set
    RANK->>NEO: extract k-hop subgraph
    RANK->>RANK: compute urgency features + weighted score
    alt score below threshold
        RANK->>NEO: write score back to nodes (no alert)
    else score crosses threshold
        RANK->>K: produce risk.scored {node, score, features}
        K->>LLM: consume risk.scored
        LLM->>RET: retrieve grounding subgraph + docs
        RET-->>LLM: evidence set (nodes, edges, citations)
        LLM->>LLM: LangGraph reason → explanation + recommendation + citations
        LLM->>K: produce reasoning.produced
        K->>NOTIF: consume reasoning.produced
        NOTIF->>NOTIF: rank vs open alerts, bundle related, dedupe by fingerprint
        alt novel + above interrupt bar
            NOTIF->>CH: deliver ranked notification
        else duplicate / low value
            NOTIF->>NOTIF: fold into digest
        end
    end
```

The two gates (score threshold, interrupt bar) are what keep this from being a spam firehose. The first bounds how often reasoning runs; the second bounds how often a human is interrupted. Both are per-org configurable — see [`docs/design/urgency-scoring.md`](../design/urgency-scoring.md) and the notification-service section of [`docs/architecture/services.md`](services.md).

---

## 3. Hybrid retrieval query

A user (or the LLM service) asks for context about an entity. Retrieval blends graph traversal, vector similarity, keyword, and filters, then fuses the rankings.

```mermaid
sequenceDiagram
    autonumber
    participant C as Caller (api-service or llm-service)
    participant RET as retrieval-service
    participant R as Redis
    participant NEO as Neo4j
    participant QD as Qdrant

    C->>RET: retrieve(query, anchor_node?, filters, org_id)
    RET->>R: cache lookup (hash of query+filters+org)
    alt cache hit
        R-->>RET: cached result set
    else cache miss
        par graph + vector + keyword
            RET->>NEO: k-hop traversal from anchor (typed, time-filtered)
            NEO-->>RET: candidate nodes + paths
        and
            RET->>QD: ANN search on query embedding (org-filtered)
            QD-->>RET: candidate nodes by similarity
        and
            RET->>NEO: keyword/property match (fulltext index)
            NEO-->>RET: candidate nodes by term
        end
        RET->>RET: reciprocal-rank fusion + relationship-aware rerank
        RET->>R: cache result set (TTL)
    end
    RET-->>C: ranked evidence set with provenance + scores
```

Graph traversal is the lead signal because relationships are the point; vector and keyword widen recall for things not yet linked. Fusion is reciprocal-rank fusion followed by a rerank that boosts candidates connected to the anchor by short, high-confidence paths. Design in [`docs/design/hybrid-retrieval.md`](../design/hybrid-retrieval.md).

---

## 4. LLM reasoning and grounding

Reasoning is a LangGraph state machine, not a single prompt. Every claim in the output must cite a graph node or edge; unsupported claims are dropped before the response leaves the service.

```mermaid
sequenceDiagram
    autonumber
    participant K as Kafka (risk.scored)
    participant G as LangGraph runtime
    participant RET as retrieval-service
    participant M as LLM (Modal/hosted)
    participant V as Grounding validator

    K->>G: risk.scored {node, features}
    G->>RET: gather_evidence(node)
    RET-->>G: evidence set (nodes, edges, citations)
    G->>M: summarize(evidence) → candidate explanation
    M-->>G: draft explanation + claims
    G->>M: recommend(evidence, explanation) → actions
    M-->>G: recommended actions
    G->>V: validate every claim maps to a citation id
    alt all claims grounded
        V-->>G: ok
        G->>K: produce reasoning.produced {explanation, actions, citations, confidence}
    else ungrounded claim found
        V-->>G: reject claim(s)
        G->>G: drop/repair claim, recompute confidence
        G->>K: produce reasoning.produced (grounded subset)
    end
```

The validator is the anti-hallucination control: the model can only assert what the evidence set supports, and the confidence attached to the notification is derived from the confidence of the citations it rests on, not from the model's own certainty. See [ADR-0007](../adr/0007-grounded-llm-reasoning.md).
