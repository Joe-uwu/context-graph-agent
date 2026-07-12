# ranking-service

Consumes `graph.changes`, scores changed subgraphs with the weighted `UrgencyScorer`,
writes urgency back to the graph, and emits `risk.scored` for nodes crossing the reason
threshold (which bounds how often the LLM stage runs). Serves on-demand scoring over HTTP.

## Topics

- Consumes: `graph.changes`
- Produces: `risk.scored`

## HTTP surface

Port `8005` (override with `CORTEX_HTTP_PORT`). `/api/v1/score` is org-scoped via `X-Org-Id`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` `/ready` `/metrics` | Ops |
| POST | `/api/v1/score` | Score a node on demand (`{node_id, hops?}`) |
| GET | `/api/v1/weights` | Urgency model weights |

## Configuration

`CORTEX_RUNTIME`, `CORTEX_NEO4J_*`, `CORTEX_REASON_AT` (default `0.60`), `CORTEX_HOPS`
(default `2`), `CORTEX_HTTP_PORT` (default `8005`), `CORTEX_OTEL_ENDPOINT`.

## Run

```bash
CORTEX_HTTP_PORT=8005 python -m cortex.services.ranking.main
docker build -f services/ranking-service/Dockerfile -t cortex/ranking-service .
docker run -p 8005:8005 cortex/ranking-service
```

## Metrics

`cortex_events_processed_total{service="ranking-service"}`, `cortex_risk_score` (histogram),
plus the shared HTTP metrics.

## Tests

```bash
pytest tests/services/test_ranking_service.py
```
