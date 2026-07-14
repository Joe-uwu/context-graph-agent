# Cortex — Proactive Enterprise Context Graph

Cortex ingests events from the systems an engineering organization already uses (GitHub, Slack, Jira, Notion, calendars, PagerDuty), maintains a live knowledge graph of the entities and relationships across them, scores what is at risk, and pushes ranked explanations to the people affected — before anyone asks.

The target output is a notification like:

> Deploy of `checkout-api` is likely to fail. PR #482 (merged 20m ago) changes `billing-client`, which Jira ticket PAY-1193 marks as blocked by incident #INC-2207 (PagerDuty, SEV-2, open 3h). The incident was discussed in `#payments-oncall` at 09:14. On-call is Dana Ito.

Nobody wrote that rule. Cortex derived it from the graph.

> **Status:** Implemented and tested. All eight services plus the dashboard run end to end — in-process with no external infrastructure (the default in-memory runtime) or against Kafka / Neo4j / Qdrant (the production runtime). CI runs unit, contract, integration (Neo4j, Qdrant, Kafka), and Playwright end-to-end jobs. See [ADR-0001](docs/adr/0001-record-architecture-decisions.md) for how decisions are tracked.

---

## Why not RAG

Retrieval-augmented generation answers a question by fetching text chunks similar to the question and letting a model summarize them. That model is reactive (it needs a question), lossy (a chunk is a flattened slice of a document, not a relationship), and stateless (it re-derives context on every call).

An enterprise question is rarely "what does this document say." It is "what depends on what, who owns it, what changed, and what is about to break." Those are graph questions. Cortex keeps the graph resident, updates it incrementally as events arrive, and runs ranking continuously in the background so that the interesting result exists before a user shows up to ask for it. Retrieval still happens — it is one input to the reasoning layer — but it is graph-first (traversal + subgraph) with vector similarity as a secondary signal, not the primary one.

| | RAG | Cortex |
|---|---|---|
| Trigger | User asks | Event arrives / continuous |
| Unit of context | Text chunk | Node + typed edges + provenance |
| State | Rebuilt per query | Resident, incrementally updated |
| Cross-source join | Implicit, in the prompt | Explicit, in the graph |
| Primary retrieval | Vector similarity | Graph traversal, then vector |
| Output | Answer | Ranked risk + explanation + recommended action |

---

## The pipeline

```
Enterprise sources (GitHub, Slack, Jira, Notion, Calendar, PagerDuty)
        │  connectors: initial sync, incremental sync, streaming
        ▼
Ingestion workers ──▶ Normalization ──▶ raw.events (Kafka)
        ▼
Entity extraction (deterministic + LLM, structured output)
        ▼
Relationship discovery ──▶ Graph writes (Neo4j)  ──▶ graph.changes (Kafka)
        ▼                                              │
Node/subgraph embeddings (Qdrant)  ◀──────────────────┘
        ▼
Background ranking workers: urgency scoring (trained GNN or weighted heuristic) over the changed subgraph
        ▼
LLM reasoning (LangGraph): grounded explanation + recommended action + citations
        ▼
Notification engine: rank, bundle, deduplicate, route (dashboard / Slack / email / webhook)
        ▼
Dashboard (Next.js): graph explorer, critical issues, recommendations, timeline
```

Every stage communicates over Kafka. Each box is an independently deployable service. The full flow and the failure/retry behaviour are in [`docs/architecture/architecture.md`](docs/architecture/architecture.md) and [`docs/architecture/sequence-diagrams.md`](docs/architecture/sequence-diagrams.md).

---

## Services

| Service | Responsibility | Reads | Writes |
|---|---|---|---|
| `ingestion-service` | Connector runtime: sync, stream, dedupe, rate-limit, retry | External APIs | `raw.events` |
| `entity-service` | Normalize events into typed entities (deterministic + LLM) | `raw.events` | `entities.extracted` |
| `graph-service` | Owns Neo4j: entity merge, relationship discovery, versioning, provenance | `entities.extracted` | Neo4j, `graph.changes` |
| `retrieval-service` | Hybrid retrieval: graph traversal + vector + keyword + filters; owns embeddings | Neo4j, Qdrant | Qdrant |
| `ranking-service` | Background urgency scoring over changed subgraphs (trained GNN or weighted heuristic) | `graph.changes`, Neo4j | `risk.scored` |
| `llm-service` | LangGraph reasoning: grounded explanation, recommendation, citations | `risk.scored`, retrieval | `reasoning.produced` |
| `notification-service` | Rank, bundle, dedupe, route notifications; digests | `reasoning.produced` | channels, `notifications.sent` |
| `api-service` | Public REST + WebSocket gateway, auth, org isolation | all stores | — |
| `dashboard` | Next.js UI: graph explorer, issues, recommendations, analytics | `api-service` | — |

The per-service contract (endpoints, consumed/produced topics, data owned) is in [`docs/architecture/services.md`](docs/architecture/services.md).

---

## Stack

Backend: Python 3.12, FastAPI, Pydantic v2, Neo4j (graph), Qdrant (vectors), Kafka (event bus). Reasoning runs on the LangGraph runtime (the nine-node graph) with any OpenAI-compatible chat model at the Reason node; the vector arm uses any OpenAI-compatible embedding model; the urgency scorer is a message-passing GNN implemented in NumPy, trained on the UCI ServiceNow incident event log. Redis (rate limits), Ray (distributed ranking), and Celery (scheduled syncs) are design targets — the current build runs ranking in-process and drives incremental sync on start and on demand.

Frontend: Next.js, TypeScript, Tailwind, shadcn/ui, React Query, React Flow + Cytoscape (graph), Recharts (analytics), Framer Motion.

Platform: Docker Compose for local, a Helm chart for Kubernetes, GitHub Actions CI. Embedding and inference use hosted OpenAI-compatible APIs, so no GPU workers are required.

Observability: OpenTelemetry tracing, Prometheus metrics, Grafana dashboards, structured JSON logging. See [ADR-0009](docs/adr/0009-observability.md).

Rationale for each major choice is an ADR under [`docs/adr/`](docs/adr/).

---

## Repository map

```
context-graph-agent/
├── README.md                    ← you are here
├── docs/
│   ├── architecture/
│   │   ├── architecture.md      C4 context/container/component, deployment
│   │   ├── sequence-diagrams.md core runtime flows
│   │   ├── services.md          per-service responsibility + contracts
│   │   └── folder-structure.md  implementation monorepo blueprint
│   ├── data/
│   │   └── graph-model.md        Neo4j node/edge catalog, constraints, ER diagram
│   ├── design/
│   │   ├── urgency-scoring.md    scoring features, weights, formula, confidence
│   │   ├── hybrid-retrieval.md   graph + vector + keyword retrieval design
│   │   └── api-and-events.md     REST/WS endpoints + Kafka envelope + topic catalog
│   ├── adr/                      architecture decision records
│   ├── deployment.md            compose → k8s, environments, scaling
│   └── onboarding.md            developer setup + contribution guide
```

## Reading order

1. This README — problem, pipeline, services.
2. [`docs/architecture/architecture.md`](docs/architecture/architecture.md) — how it fits together.
3. [`docs/data/graph-model.md`](docs/data/graph-model.md) — the graph everything revolves around.
4. [`docs/design/urgency-scoring.md`](docs/design/urgency-scoring.md) — how "what matters" is computed.
5. [`docs/adr/`](docs/adr/) — why the choices were made.

---

## Scope of this phase

All eight services and the dashboard are implemented and covered by CI. Every source ships a real connector (GitHub, Slack, Jira, Notion, Google Calendar, PagerDuty) plus a synthetic mock twin behind the same interface, so the platform runs end to end with no live accounts and switches to real credentials by configuration (see [ADR-0003](docs/adr/0003-connector-framework.md)). The reasoning graph runs on LangGraph, the embedder and reasoner call OpenAI-compatible endpoints, and the urgency scorer is a trained GNN — each behind a port with an offline default so nothing is required to run the pipeline. Distributed execution (Ray), scheduled syncs (Celery), and Postgres cursor persistence remain design targets; the current build runs the pipeline in-process or over Kafka. What is real vs. optional is detailed in [`CODE_README.md`](CODE_README.md).
