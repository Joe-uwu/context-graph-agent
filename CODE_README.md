# Cortex — reference implementation

This is the runnable implementation of the platform designed in [`docs/`](docs/). It runs
the entire pipeline — synthetic enterprise events → ingestion → entity extraction →
context graph → urgency scoring → grounded reasoning → notifications — end to end, with
**no external infrastructure required** for the default (in-memory) runtime.

For the architecture, graph model, scoring design, and ADRs, start with [`README.md`](README.md).

## Layout

The monorepo follows the blueprint in [`docs/architecture/folder-structure.md`](docs/architecture/folder-structure.md):

```
packages/   contracts, platform, graph_sdk      (shared libraries)
services/   ingestion, entity, graph, retrieval, ranking, llm, notification, api
tools/      synthetic event generator + in-process pipeline runner
tests/      unit / integration / e2e
infra/      docker-compose, k8s, grafana
apps/       dashboard (Next.js)
```

Every service and package is its own installable distribution with its own
`pyproject.toml` and (for services) a `Dockerfile`, so each deploys independently. The
`cortex.*` namespace is a PEP 420 namespace package spread across those source roots.

## Two runtimes, one codebase

Services depend only on ports (`EventBus`, `GraphRepository`, `Reasoner`, …). The runtime
picks the implementation:

- **memory** (default): `InMemoryEventBus` + `InMemoryGraphRepository`. The whole pipeline
  runs in one process. No Kafka, Neo4j, Qdrant, or credentials needed. This is what the
  demo and tests use.
- **kafka**: `KafkaEventBus` + `Neo4jGraphRepository` + Qdrant. Each service runs as its
  own process/container consuming from Kafka. Brought up by `docker compose`.

The route layer, extractors, scorer, reasoner, and notification engine are identical
across both. Only the composition root differs.

## Run it

Requirements for the in-memory path: Python 3.11+ and `pip`. Nothing else.

```bash
pip install -e .                 # installs the whole workspace
cortex-demo                      # run the deploy-will-fail scenario end to end
cortex-synth                     # print the synthetic source events as JSON
```

`cortex-demo` prints the context graph size, the ranked risks, and the single bundled,
grounded notification the graph produced — the cross-source "your deploy will fail"
alert that no individual source could have raised.

Serve the API over the live in-memory pipeline:

```bash
pip install -e ".[api]"
uvicorn cortex.services.api.server:app --reload   # http://localhost:8000/docs
```

Full stack (Kafka/Neo4j/Qdrant/Redis/Postgres + all services + dashboard):

```bash
make up      # docker compose up
make seed    # push the synthetic scenario through the real bus
make down
```

## Test

```bash
pip install -e ".[dev,api]"
pytest                 # unit + integration + e2e
ruff check .           # lint
mypy                   # type check (strict)
```

The e2e test asserts the pipeline joins at least four sources into one graph, that risk
scores spread rather than saturate, and that exactly one grounded interrupt is produced
for the incident cluster.

## What is real vs. stubbed

Real and exercised end to end: the event envelope and contracts, the in-memory bus with
retry/DLQ, deterministic entity extraction, entity resolution and idempotent graph writes
with provenance/temporal edges, k-hop traversal, the weighted urgency scorer, hybrid
retrieval (graph + keyword arms), grounded reasoning with the citation validator, and
notification bundling/routing.

Real interface, wiring left for credentials/infra (with a working mock twin so the
pipeline still runs): the six source connectors' live API calls, the Kafka bus, the Neo4j
and Qdrant adapters, the embedding/vector arm, the LangGraph/LLM reasoner, and the GNN
scorer. Each is a drop-in behind a port that the in-memory default already satisfies. See
the ADRs for why each boundary sits where it does.
