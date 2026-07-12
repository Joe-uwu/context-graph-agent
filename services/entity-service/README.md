# entity-service

Consumes `raw.events`, runs deterministic entity extraction (typed nodes + edges), and
publishes `entities.extracted`. Stateless transform: it holds no store, so it scales
horizontally and the extraction is exposed synchronously over HTTP for inspection/testing.

## Topics

- Consumes: `raw.events`
- Produces: `entities.extracted`

## HTTP surface

Port `8002` (override with `CORTEX_HTTP_PORT`).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness |
| GET | `/metrics` | Prometheus metrics |
| POST | `/api/v1/extract` | Extract entities from a `RawEvent` body |
| GET | `/api/v1/stats` | Events processed + nodes extracted |

`POST /api/v1/extract` takes a `RawEvent` JSON body and returns the `EntitiesExtracted`
payload with node/edge counts — the same output the consumer emits.

## Configuration

Environment variables (prefix `CORTEX_`): `CORTEX_RUNTIME`, `CORTEX_KAFKA_BOOTSTRAP`,
`CORTEX_HTTP_PORT` (default `8002`), `CORTEX_LOG_LEVEL`, `CORTEX_OTEL_ENDPOINT`.

## Run

```bash
CORTEX_HTTP_PORT=8002 python -m cortex.services.entity.main
docker build -f services/entity-service/Dockerfile -t cortex/entity-service .
docker run -p 8002:8002 cortex/entity-service
```

## Metrics

`cortex_events_processed_total{service="entity-service"}`, plus the shared HTTP metrics.

## Tests

```bash
pytest tests/services/test_entity_service.py
```
