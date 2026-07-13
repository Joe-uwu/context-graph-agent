# Testing

Every layer is exercised; the ones that need infrastructure run against real service
containers in CI and skip cleanly offline.

## Layers

| Layer | Where | Runs offline? |
| --- | --- | --- |
| Unit | `tests/unit/` — scoring, grounding, embeddings, reasoning graph, Neo4j helpers | yes |
| Wire contract | `tests/contract/test_event_contract.py` — envelope, payloads, topics, enum stability | yes |
| Repository contract | `tests/contract/test_repository_contract.py` — same suite vs in-memory + real Neo4j | memory only |
| Vector contract | `tests/contract/test_vector_index.py` — in-memory + real Qdrant (`:memory:` or server) | both |
| Service (API) | `tests/services/` — every service's HTTP surface via FastAPI TestClient | yes |
| Integration | `tests/integration/test_api.py` (gateway), `test_kafka_bus.py` (real broker) | api yes, kafka skips |
| End-to-end (pipeline) | `tests/e2e/test_pipeline.py` — full in-process pipeline, one grounded interrupt | yes |
| End-to-end (browser) | `apps/dashboard/e2e/` — Playwright over the dashboard | needs node + browser |

## Run

```bash
pip install -e ".[dev,api,github]"
pytest -q                       # unit + contract + service + integration(api) + e2e
ruff check .                    # lint
mypy                            # types

cortex-demo                     # the deploy-will-fail scenario end to end (prints the alert)
```

Infra-backed suites when you have the services (or let CI run them):

```bash
CORTEX_NEO4J_URI=bolt://localhost:7687 pytest tests/contract/test_repository_contract.py
CORTEX_QDRANT_URL=http://localhost:6333 pytest tests/contract/test_vector_index.py
CORTEX_KAFKA_BOOTSTRAP=localhost:9092   pytest tests/integration/test_kafka_bus.py

cd apps/dashboard/e2e && npm install && npx playwright install --with-deps chromium && npx playwright test
```

## CI (`.github/workflows/ci.yml`)

`test` (pytest + advisory lint/type) → then in parallel: `build-and-smoke` (8 service images
build + boot), `compose-smoke` (full kafka-runtime stack), `graph-it` (Neo4j), `vector-it`
(Qdrant), `kafka-it` (Kafka), `dashboard-e2e` (Playwright). All are hard gates except the
advisory lint/type steps.
