# api-service

The read gateway. Serves the REST API the dashboard consumes: top risks, node lookup,
neighborhood, search, and the notification feed. In the local/demo runtime it builds the
in-memory pipeline, seeds it with the synthetic scenario, and serves over that live state, so
the dashboard has data with no external infrastructure.

## HTTP surface

Port `8000` (override with `CORTEX_HTTP_PORT`). All `/api` routes are org-scoped via the
`X-Org-Id` header (a real deployment resolves org_id from the caller's JWT).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` `/ready` `/metrics` | Ops |
| GET | `/api/v1/risk/top?limit=&min_score=` | Top nodes by urgency |
| GET | `/api/v1/graph/nodes/{node_id}` | Node with its edges |
| GET | `/api/v1/graph/nodes/{node_id}/neighborhood?hops=` | k-hop subgraph |
| POST | `/api/v1/search` | Hybrid search (`{query, limit}`) |
| GET | `/api/v1/notifications` | Notification feed |

Every response uses the envelope `{ "data": ..., "meta": {...}, "errors": [] }`. OpenAPI is at
`/openapi.json`, interactive docs at `/docs`.

## Configuration

`CORTEX_RUNTIME`, `CORTEX_HTTP_PORT` (default `8000`), `CORTEX_OTEL_ENDPOINT`.

## Run

```bash
# Local (in-memory), seeded with the synthetic scenario
uvicorn cortex.services.api.server:app --host 0.0.0.0 --port 8000

docker build -f services/api-service/Dockerfile -t cortex/api-service .
docker run -p 8000:8000 cortex/api-service
```

## Metrics

`api_risk_top_requests_total`, plus the shared HTTP metrics
(`cortex_http_requests_total`, `cortex_http_request_duration_seconds`).

## Tests

```bash
pytest tests/integration/test_api.py
```
