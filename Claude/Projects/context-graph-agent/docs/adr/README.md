# Architecture Decision Records

Each ADR records one decision: the context that forced it, the decision, the consequences (good and bad), and the alternatives rejected. ADRs are immutable once accepted; a reversal is a new ADR that supersedes an old one. Format follows Michael Nygard's template.

| # | Decision | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-event-driven-microservices.md) | Event-driven microservices over Kafka | Accepted |
| [0003](0003-connector-framework.md) | Connector framework with real + mock twins | Accepted |
| [0004](0004-repository-pattern.md) | Repository pattern and single-writer per store | Accepted |
| [0005](0005-neo4j-context-store.md) | Neo4j as the context graph store | Accepted |
| [0006](0006-qdrant-vectors.md) | Qdrant for vector retrieval | Accepted |
| [0007](0007-grounded-llm-reasoning.md) | Grounded LLM reasoning with LangGraph | Accepted |
| [0008](0008-auth-and-tenancy.md) | Auth and multi-tenant isolation | Accepted |
| [0009](0009-observability.md) | Observability with OpenTelemetry, Prometheus, Grafana | Accepted |
| [0010](0010-gnn-urgency-scorer.md) | Optional GNN urgency scorer | Proposed |
| [0011](0011-ray-distributed-ranking.md) | Ray for distributed background ranking | Accepted |
