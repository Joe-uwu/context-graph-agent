# Developer onboarding and contributing

## First hour

1. Read the [README](../README.md) — problem, pipeline, services.
2. Read [`architecture/architecture.md`](architecture/architecture.md) and [`data/graph-model.md`](data/graph-model.md). The graph is the center of the system; understand its node/edge model before touching a service.
3. Skim the [ADR log](adr/README.md). It explains why the non-obvious choices were made.
4. `make up && make seed` to bring the platform up locally with a synthetic demo org, then open the dashboard and watch a synthetic incident propagate into a grounded notification.

## Local setup

Prerequisites: Docker + Compose, Python 3.12, `uv` (or Poetry), Node 20+, `make`. No cloud accounts or source credentials are needed for local dev — connectors default to their mock twins.

```
make dev        # install workspace deps (python + node), set up pre-commit hooks
make up         # start infra + services under Compose
make seed       # populate a demo org from tools/synthetic
make test       # unit + integration suites
```

To run a single service against the shared local infra, `cd services/<name>-service && make run` (each service README documents its env vars and the topics it consumes/produces).

## How to make a change

The dependency rule is the thing to keep straight: `domain` depends on nothing, `application` on `domain` + `ports`, `adapters` implement `ports`, frameworks live only in `adapters`/`api`. If you find yourself importing the Neo4j driver or FastAPI into `domain`, stop — that logic belongs in an adapter.

- Changing the graph: it goes through `graph-service` and the `graph-sdk` repository. Never write Neo4j from another service (see [ADR-0004](adr/0004-repository-pattern.md)).
- Changing an event's shape: edit the schema in `packages/contracts`, bump `schema_version` if not additive, and the CI compat check will tell you which consumers break.
- Adding a source: implement the connector interface in `ingestion-service` plus a mock twin (see [ADR-0003](adr/0003-connector-framework.md)); add its node/edge types to the graph model if new.
- Adding a node or edge type: update `docs/data/graph-model.md`, the constraints, and the extraction rules in `entity-service`.

## Definition of done

A change is done when: unit + integration tests pass, `ruff` and `mypy` are clean (no `any`), any new public behavior has a test, docs affected by the change are updated in the same PR, and — for changes to reasoning or scoring — the e2e slice still produces a grounded notification. Type checking is not optional; the repository is fully typed and `mypy` runs in CI.

## Contributing

Branch, implement, keep the PR scoped to one concern. PRs run the full CI gate (lint, type-check, unit, integration, image build, contract compat). Every architectural decision that changes the shape of the system gets an ADR in the same PR. Pre-commit hooks run `ruff` and `mypy` so red CI is rare. Reviews check the dependency rule, tenant scoping (every query carries `org_id`), and grounding (no reasoning path that can assert an uncited claim).

## Where things live

- A service's behavior and contracts: `services/<name>-service/README.md`.
- The wire format: `packages/contracts`.
- Why a decision was made: `docs/adr/`.
- How to run/scale it in prod: `docs/deployment.md`.
