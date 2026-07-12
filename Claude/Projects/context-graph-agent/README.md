# Cortex — Proactive Enterprise Context Graph

Cortex ingests events from the systems an engineering organization already uses (GitHub, Slack, Jira, Notion, calendars, PagerDuty), maintains a live knowledge graph of the entities and relationships across them, scores what is at risk, and pushes ranked explanations to the people affected — before anyone asks.

The target output is a notification like:

> Deploy of `checkout-api` is likely to fail. PR #482 (merged 20m ago) changes `billing-client`, which Jira ticket PAY-1193 marks as blocked by incident #INC-2207 (PagerDuty, SEV-2, open 3h). The incident was discussed in `#payments-oncall` at 09:14. On-call is Dana Ito.

Nobody wrote that rule. Cortex derived it from the graph.

> **Status:** Design phase. This repository currently contains the architecture and system design (`/docs`). No runtime code has been written yet; the folder blueprint in [`docs/architecture/folder-structure.md`](docs/architecture/folder-structure.md) describes what the implementation will fill in. See [ADR-0001](docs/adr/0001-record-architecture-decisions.md) for how decisions are tracked.

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
Background ranking workers (Ray): urgency scoring over changed subgraph
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
| `ranking-service` | Background urgency scoring over changed subgraphs (Ray workers) | `graph.changes`, Neo4j | `risk.scored` |
| `llm-service` | LangGraph reasoning: grounded explanation, recommendation, citations | `risk.scored`, retrieval | `reasoning.produced` |
| `notification-service` | Rank, bundle, dedupe, route notifications; digests | `reasoning.produced` | channels, `notifications.sent` |
| `api-service` | Public REST + WebSocket gateway, auth, org isolation | all stores | — |
| `dashboard` | Next.js UI: graph explorer, issues, recommendations, analytics | `api-service` | — |

The per-service contract (endpoints, consumed/produced topics, data owned) is in [`docs/architecture/services.md`](docs/architecture/services.md).

---

## Stack

Backend: Python 3.12, FastAPI, LangGraph, Pydantic v2, SQLAlchemy (relational metadata), Neo4j (graph), Qdrant (vectors), Redis (cache + rate limits), Kafka (event bus), Ray (distributed ranking), Celery (scheduled connector syncs), PyTorch (embeddings / optional GNN scorer).

Frontend: Next.js, TypeScript, Tailwind, shadcn/ui, React Query, React Flow + Cytoscape (graph), Recharts (analytics), Framer Motion.

Platform: Docker Compose for local, Kubernetes-ready manifests, GitHub Actions CI, Terraform-ready layout, Modal for GPU embedding/inference workers.

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

Design only. No services run yet. Where the design references real integrations (GitHub, Slack, Jira, etc.) the plan is to ship a mock connector and a synthetic event generator alongside each real one, so the platform can be demonstrated end-to-end without live enterprise accounts and switched to real credentials without architectural change (see [ADR-0003](docs/adr/0003-connector-framework.md)).
