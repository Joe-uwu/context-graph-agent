# Folder structure blueprint

The implementation is a monorepo: Python services and shared packages under `services/` and `packages/`, the Next.js app under `apps/`, infrastructure under `infra/`, and this `docs/` tree. A monorepo keeps the shared contract (`packages/contracts`) and every service that depends on it in one place, so a wire-format change and all its consumers move in one atomic PR and one CI run. Services are still built and deployed as separate images.

```
context-graph-agent/
├── README.md
├── docs/                          ← this design set (the only populated tree today)
│   ├── architecture/  data/  design/  adr/
│   ├── deployment.md  onboarding.md
├── packages/                      ← shared libraries (imported, not deployed)
│   ├── contracts/                 event envelope, payload schemas, enums (Pydantic)
│   ├── platform/                  Kafka wrappers, OTel, logging, Redis, config, health
│   └── graph-sdk/                 typed Neo4j repository, Cypher builders, temporal helpers
├── services/                      ← one deployable per subdir
│   ├── ingestion-service/
│   ├── entity-service/
│   ├── graph-service/
│   ├── retrieval-service/
│   ├── ranking-service/
│   ├── llm-service/
│   ├── notification-service/
│   └── api-service/
├── apps/
│   └── dashboard/                 Next.js + TypeScript
├── infra/
│   ├── compose/                   docker-compose.yml + per-store configs (local)
│   ├── k8s/                       manifests / Helm / Kustomize overlays
│   ├── terraform/                 cloud infra (VPC, managed Kafka/Neo4j, etc.)
│   └── grafana/                   dashboards + alert rules as code
├── tools/
│   ├── synthetic/                 cross-source event generator for demos + tests
│   └── scripts/                   dev scripts, seed, migrate
├── .github/workflows/             CI: lint, type-check, test, build, compat-check
├── pyproject.toml                 workspace config (uv/poetry), ruff, mypy
├── docker-compose.yml             top-level local bring-up
└── Makefile                       make dev / test / lint / up / down
```

## Per-service module template

Every service under `services/` follows the same internal shape (clean/hexagonal architecture), so a contributor who learns one learns all of them:

```
services/<name>-service/
├── src/<name>_service/
│   ├── domain/          entities, value objects, domain logic — no I/O, no framework
│   ├── application/     use cases / handlers orchestrating domain + ports
│   ├── ports/           interfaces the application depends on (repositories, publishers)
│   ├── adapters/        concrete implementations of ports (Neo4j, Kafka, HTTP clients)
│   ├── api/             FastAPI routers (services that expose HTTP)
│   ├── workers/         Kafka consumers / Ray / Celery entrypoints
│   ├── config.py        typed settings (pydantic-settings), env-driven
│   └── main.py          composition root: wire adapters into ports (DI)
├── tests/
│   ├── unit/            domain + application, no external deps
│   ├── integration/     against real Neo4j/Kafka/Qdrant via testcontainers
│   └── e2e/             pipeline slice through the bus
├── Dockerfile
├── pyproject.toml
└── README.md            what it consumes/produces, how to run it alone
```

The dependency rule points inward: `domain` depends on nothing, `application` depends on `domain` and `ports`, `adapters` depend on `ports`. Frameworks (FastAPI, the Neo4j driver, Kafka) live only in `adapters` and `api`, so the core logic is testable without them and a store or transport can be swapped by writing a new adapter. `main.py` is the only place that knows the concrete wiring — dependency injection at the composition root, not scattered globals.

## Testing layers

Unit tests cover `domain` and `application` with ports mocked — fast, run on every commit. Integration tests run each service's adapters against real backing stores spun up with testcontainers, so the Cypher and the Kafka wiring are exercised for real. End-to-end tests push a synthetic event through a slice of the bus (ingestion → graph → ranking → notification) and assert the notification comes out grounded. The synthetic generator in `tools/synthetic/` produces the fixtures for both integration and e2e.

## CI

`.github/workflows/` runs, per PR: ruff (lint + format check), mypy (type check, no `any`), the unit suite, the integration suite (testcontainers), a build of each changed service image, and the contract compatibility check that fails if a payload schema change breaks an existing consumer. Pre-commit hooks run ruff and mypy locally so red CI is rare. Green CI is the bar for merge.
