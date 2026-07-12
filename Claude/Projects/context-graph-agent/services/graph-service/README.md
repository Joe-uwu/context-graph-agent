# graph-service

The sole writer of the context graph. Consumes `entities.extracted`, resolves entities and
writes them with idempotent MERGE (provenance, confidence, temporal edges), discovers
relationships, and emits `graph.changes`. Serves read access to the graph over HTTP.

## Topics

- Consumes: `entities.extracted`
- Produces: `graph.changes`

## HTTP surface

Port `8003` (override with `CORTEX_HTTP_PORT`). All `/api` routes are org-scoped via the
`X-Org-Id` header.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` `/ready` `/metrics` | Ops |
| GET | `/api/v1/nodes/{node_id}` | Node with its current edges |
| GET | `/api/v1/nodes/{node_id}/neighborhood?hops=` | k-hop subgraph (1–4 hops) |
| GET | `/api/v1/stats` | Per-tenant node count by label |

## Configuration

`CORTEX_RUNTIME` (`memory`/`kafka`), `CORTEX_NEO4J_URI`, `CORTEX_NEO4J_USER`,
`CORTEX_NEO4J_PASSWORD` (kafka runtime), `CORTEX_HTTP_PORT` (default `8003`),
`CORTEX_OTEL_ENDPOINT`.

In `memory` runtime the graph is an in-process `InMemoryGraphRepository`; in `kafka`
runtime it is `Neo4jGraphRepository`.

## Run

```bash
CORTEX_HTTP_PORT=8003 python -m cortex.services.graph.main
docker build -f services/graph-service/Dockerfile -t cortex/graph-service .
docker run -p 8003:8003 cortex/graph-service
```

## Metrics

`cortex_events_processed_total{service="graph-service"}`,
`cortex_graph_nodes_upserted_total`, plus the shared HTTP metrics.

## Tests

```bash
pytest tests/services/test_graph_service.py
```
