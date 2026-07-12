# Services

Nine deployable units. Each has a single responsibility, owns at most one datastore, and communicates with the rest only over Kafka (or, for the edge tier, HTTP). This table is the quick reference; the sections below give the detail.

| Service | Consumes | Produces | Owns | Scale trigger |
|---|---|---|---|---|
| ingestion-service | (external APIs, webhooks) | `raw.events` | sync cursors (PG) | source event rate |
| entity-service | `raw.events` | `entities.extracted` | — | extraction backlog |
| graph-service | `entities.extracted`, `user.actions` | `graph.changes` | Neo4j | write rate |
| retrieval-service | `graph.changes` | (serves queries) | Qdrant | query + embed load |
| ranking-service | `graph.changes` | `risk.scored` | — (Ray) | change churn |
| llm-service | `risk.scored` | `reasoning.produced` | — | reasoning backlog |
| notification-service | `reasoning.produced`, `user.actions` | `notifications.sent` | notif store (PG) | alert volume |
| api-service | (all stores, WS bridge) | `user.actions` | — | request rate |
| dashboard | (api-service) | — | — | user count |

---

## ingestion-service

The connector runtime. One connector per source, all implementing a common interface (see [ADR-0003](../adr/0003-connector-framework.md)): `initial_sync`, `incremental_sync`, `stream` (webhook/socket), with shared machinery for pagination, rate limiting (token bucket in Redis), retry with exponential backoff and jitter, and deduplication by source delivery id. Sync cursors persist in Postgres so a restart resumes rather than refetches. Celery beat schedules incremental syncs for sources without push. Output is normalized into the common event envelope and produced to `raw.events`. Every source ships a real connector and a mock/synthetic-generator twin behind the same interface so the platform runs end-to-end without live accounts.

## entity-service

Turns a raw event into typed entities and candidate relationships. Two-tier extraction: deterministic parsers pull the certain structure (a PR's author, number, changed files; a Jira ticket's key, status, links) at confidence 1.0; an LLM pass with a structured (Pydantic-constrained) output pulls the fuzzy structure (which services a change touches, what a Slack thread is about, intent). The LLM never invents ids — it classifies and links within the entities the deterministic tier already found. Produces `entities.extracted`.

## graph-service

The only writer of Neo4j. Resolves entities against existing nodes (dedupe, `ALIAS_OF` for cross-source identity), runs three-tier relationship discovery (rule → embedding → LLM residue), writes idempotent `MERGE` Cypher with provenance/confidence/temporal stamps, and closes edges that are no longer asserted instead of deleting them. Emits `graph.changes` with the touched node ids. Also consumes `user.actions` so an ack/dismiss updates node state. Detail in [`docs/data/graph-model.md`](../data/graph-model.md).

## retrieval-service

Owns embeddings and hybrid retrieval. On `graph.changes` it re-embeds affected nodes/subgraphs/documents and upserts to Qdrant. Serves retrieval requests (from `api-service` and `llm-service`) by running the graph/vector/keyword arms, fusing with RRF, and reranking by relationship proximity. Detail in [`docs/design/hybrid-retrieval.md`](../design/hybrid-retrieval.md).

## ranking-service

Background urgency scoring on Ray. Consumes `graph.changes`, debounces bursts, extracts k-hop subgraphs around changed nodes, fans scoring across Ray workers, writes scores back to Neo4j, and emits `risk.scored` for nodes crossing the reasoning threshold. Cost scales with churn, not graph size. Optional GNN scorer on Modal. Detail in [`docs/design/urgency-scoring.md`](../design/urgency-scoring.md).

## llm-service

LangGraph reasoning. Consumes `risk.scored`, gathers evidence via `retrieval-service`, and runs a state machine: summarize evidence → draft explanation → recommend actions → validate grounding. The grounding validator drops any claim not backed by a citation id before emitting `reasoning.produced` (explanation, actions, citations, confidence). Confidence is inherited from the evidence, not the model's self-assessment. Detail in [ADR-0007](../adr/0007-grounded-llm-reasoning.md).

## notification-service

Decides who gets told what, and whether it is worth an interruption. Consumes `reasoning.produced`, ranks against currently-open alerts, bundles related items (same incident, same deployment), deduplicates by a content fingerprint so the same risk is not re-sent as it re-scores, and routes above-bar items to channels (Slack, email, webhook, dashboard) while folding the rest into a daily digest. Consumes `user.actions` so an acked or snoozed alert stops re-firing. Produces `notifications.sent` for analytics. The two gates that prevent spam (reason threshold, interrupt bar) are described in [`docs/design/urgency-scoring.md`](../design/urgency-scoring.md) and [`docs/architecture/sequence-diagrams.md`](sequence-diagrams.md).

## api-service

The public edge. FastAPI REST + WebSocket, JWT auth, org scoping, RED metrics, OpenAPI docs. Reads across Neo4j/Qdrant/Postgres/Redis but mutates no pipeline store directly — user actions become `user.actions` events so the pipeline stays the single writer. Bridges selected Kafka topics to WebSocket subscribers for the live dashboard. Contract in [`docs/design/api-and-events.md`](../design/api-and-events.md).

## dashboard

Next.js + TypeScript app. Pages: Overview, Graph Explorer (React Flow / Cytoscape over the live graph), Critical Issues, Recommendations, Timeline ("what changed"), Repositories / People / Teams / Projects / Incidents, Notifications inbox, Risk Analytics (Recharts). Dark mode, React Query for data, WebSocket for live updates. Talks only to `api-service`.

---

## Shared packages (not services)

These are libraries every service imports, not deployables:

- `contracts` — the event envelope, all payload schemas, shared enums. Single source of truth for the wire format.
- `platform` — cross-cutting infra: Kafka producer/consumer wrappers, OTel setup, structured logging, Redis client, config loading, health-check helpers.
- `graph-sdk` — typed Neo4j repository (Cypher builders, constraint definitions, temporal query helpers) used by graph-service, retrieval-service, ranking-service, api-service.

Keeping these as packages rather than a shared service avoids a network hop for what is really just code, while still giving one place to change the contract. See [`docs/architecture/folder-structure.md`](folder-structure.md).
