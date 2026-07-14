# Cortex — proactive enterprise context graph platform

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

## What is real vs. optional

The whole pipeline runs end to end with zero credentials on offline defaults. Every external
boundary also has a real implementation behind the same port, switched on by configuration:

- Source connectors: all six (GitHub, Slack, Jira, Notion, Google Calendar, PagerDuty) make
  authenticated API calls with pagination, retry/backoff, and rate-limit handling, and
  normalize to the shared RawEvent. Each `build_*_connector` returns None when its
  `CORTEX_<SOURCE>_*` credentials are absent, so the service falls back to the synthetic mock
  twin and stays up. GitHub also has an HMAC-verified webhook receiver.
- Embedder: `OpenAIEmbedder` calls any OpenAI-compatible `/v1/embeddings` endpoint
  (`CORTEX_EMBEDDING_PROVIDER=openai`); the offline `HashingEmbedder` is the default.
- Reasoner: the reasoning graph's Reason node calls any OpenAI-compatible chat endpoint
  (`CORTEX_LLM_PROVIDER=openai`), with the grounding validator gating every citation and a
  deterministic template as the fallback when no LLM is configured or a call fails. The nine
  nodes run on a hand-rolled typed-state engine by default or, with
  `CORTEX_REASONER_ENGINE=langgraph`, compile onto the real LangGraph runtime unchanged.
- Urgency scorer: a trained message-passing GNN (`CORTEX_SCORER_MODEL=gnn`) scores each
  changed subgraph — the model and its NumPy forward/backprop live in `services/ranking/gnn/`.
  It trains either on the real UCI ServiceNow incident event log (24,918 incidents with real
  impact/urgency/priority labels; see `gnn/README.md`) or on a synthetic generator for
  reproducibility without the dataset. The transparent weighted heuristic is the default and the
  fallback when weights or NumPy are absent.

Real and exercised end to end on the offline defaults: the event envelope and contracts, the
in-memory bus with retry/DLQ, deterministic entity extraction, entity resolution and
idempotent graph writes with provenance/temporal edges, k-hop traversal, urgency scoring,
hybrid retrieval (graph + keyword + vector arms), grounded reasoning with the citation
validator, and notification bundling/routing.

Swap-in-by-config for infra, with the in-memory default satisfying the same port: the Kafka
bus and the Neo4j and Qdrant adapters. See the ADRs for why each boundary sits where it does.
