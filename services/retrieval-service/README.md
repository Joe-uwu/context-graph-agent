# retrieval-service

Hybrid retrieval and evidence gathering. Consumes `graph.changes` to keep the vector index
current (no-op index by default until a Qdrant-backed `VectorIndex` is wired in), and serves
search + k-hop evidence gathering over HTTP to llm-service and api-service.

## Topics

- Consumes: `graph.changes`

## HTTP surface

Port `8004` (override with `CORTEX_HTTP_PORT`). `/api` routes are org-scoped via `X-Org-Id`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` `/ready` `/metrics` | Ops |
| POST | `/api/v1/search` | Hybrid graph+keyword search (`{query, limit}`) |
| GET | `/api/v1/evidence/{node_id}?hops=` | k-hop evidence subgraph for a node |

## Configuration

`CORTEX_RUNTIME`, `CORTEX_NEO4J_*`, `CORTEX_QDRANT_URL`, `CORTEX_HTTP_PORT` (default `8004`),
`CORTEX_EVIDENCE_HOPS` (default `2`), `CORTEX_OTEL_ENDPOINT`.

## Run

```bash
CORTEX_HTTP_PORT=8004 python -m cortex.services.retrieval.main
docker build -f services/retrieval-service/Dockerfile -t cortex/retrieval-service .
docker run -p 8004:8004 cortex/retrieval-service
```

## Metrics

`cortex_retrieval_queries_total`, `cortex_events_processed_total{service="retrieval-service"}`,
plus the shared HTTP metrics.

## Tests

```bash
pytest tests/services/test_retrieval_service.py
```
