# ingestion-service

Pulls events from source connectors, normalizes them into `RawEvent`s, and publishes them
to the `raw.events` topic. Connectors default to a mock twin seeded from the synthetic
generator, so the service runs with no credentials; real connectors (GitHub first) register
when their credentials are present.

## Topics

- Produces: `raw.events`

## HTTP surface

Port `8001` (override with `CORTEX_HTTP_PORT`).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness (503 until initial sync scheduled) |
| GET | `/metrics` | Prometheus metrics |
| GET | `/api/v1/connectors` | Registered source connectors |
| POST | `/api/v1/sync` | Trigger a backfill of every connector |
| GET | `/api/v1/stats` | Connector count + events published |
| POST | `/webhooks/github` | GitHub webhook receiver (HMAC-verified) |

## Connectors

The GitHub connector is fully implemented (OAuth / GitHub App / PAT auth, paginated +
rate-limited REST client, incremental sync, and HMAC-verified webhooks) — see
[`connectors/github/README.md`](src/cortex/services/ingestion/connectors/github/README.md).
Configure it with `CORTEX_GITHUB_*` (at minimum `CORTEX_GITHUB_ORG` plus one credential:
`CORTEX_GITHUB_TOKEN`, an OAuth refresh token, or GitHub App keys) and set
`CORTEX_GITHUB_WEBHOOK_SECRET` to accept webhook deliveries. With no credentials the service
runs on the synthetic mock twin. The remaining sources (Slack, Jira, Notion, Calendar,
PagerDuty) follow the same pattern and are next in the roadmap.

OpenAPI is served at `/openapi.json` and interactive docs at `/docs`.

## Configuration

Environment variables (prefix `CORTEX_`):

| Var | Default | Meaning |
| --- | --- | --- |
| `CORTEX_RUNTIME` | `memory` | `memory` (in-process) or `kafka` (real bus) |
| `CORTEX_KAFKA_BOOTSTRAP` | `localhost:9092` | Kafka brokers (kafka runtime) |
| `CORTEX_ORG_ID` | `org_demo` | Tenant this process ingests for |
| `CORTEX_SEED_SYNTHETIC` | `true` | Register the synthetic mock connector |
| `CORTEX_RUN_INITIAL_SYNC` | `true` | Backfill once on start |
| `CORTEX_HTTP_PORT` | `8001` | HTTP port |
| `CORTEX_OTEL_ENDPOINT` | unset | OTLP endpoint for traces |

## Run

```bash
# Local (in-memory), from the repo root with the workspace installed (pip install -e ".[dev]")
CORTEX_HTTP_PORT=8001 python -m cortex.services.ingestion.main

# Container
docker build -f services/ingestion-service/Dockerfile -t cortex/ingestion-service .
docker run -p 8001:8001 cortex/ingestion-service
```

## Metrics

`cortex_events_published_total{source}`, `cortex_http_requests_total`,
`cortex_http_request_duration_seconds`.

## Tests

```bash
pytest tests/services/test_ingestion_service.py
```
