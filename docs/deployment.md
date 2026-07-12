# Deployment

Three environments, one topology, increasing scale: local (Docker Compose), staging/production (Kubernetes), with cloud infra defined in Terraform. The service boundaries are identical across all three; only the backing-store deployment and replica counts change.

## Local — Docker Compose

`docker compose up` from the repo root brings up the full platform against single-node infrastructure: Kafka (single broker), Neo4j (single instance), Qdrant, Postgres, Redis, all eight services, and the dashboard. Ray runs in local mode inside `ranking-service`. GPU stages fall back to CPU or a hosted embedding/inference API (configured by env). Connectors default to their mock twins driven by `tools/synthetic/`, so nothing needs real credentials. The OTel collector, Prometheus, and Grafana come up alongside so tracing and dashboards work locally.

```
make up        # docker compose up -d, wait for health
make seed      # run synthetic generator to populate a demo org
make logs      # tail all services
make down      # tear down
```

Target: a working end-to-end demo (synthetic incident → graph → risk → grounded notification on the dashboard) on a laptop, no external accounts.

## Staging / production — Kubernetes

Manifests in `infra/k8s/`, organized into four namespaces mirroring the tiers in the architecture doc (edge, processing, ingestion, data). Each service is a Deployment with an HPA; the scale signal per service is in `docs/architecture/services.md` (ingestion on event rate, ranking on change churn, llm on backlog, api on request rate). Kafka is run via an operator (Strimzi), Neo4j as a causal cluster, Qdrant and Redis clustered, Postgres managed. Ray runs as a cluster (head + autoscaling worker group). GPU stages schedule onto Modal or a GPU node pool.

Rollouts are per-service rolling updates; because the bus decouples stages, a service can be redeployed without coordinated downtime — in-flight events queue and resume. Schema changes to events are additive within a major version (enforced by the CI compat check), so a new consumer and old producers coexist during a rollout.

## Scaling knobs

| Concern | Knob |
|---|---|
| Ingestion throughput | connector concurrency + `raw.events` partitions + consumer replicas |
| Graph write rate | `entities.extracted` partitions + graph-service replicas (per-org ordering preserved by partition key) |
| Ranking freshness under churn | Ray worker count + debounce window |
| Reasoning backlog | llm-service replicas + Modal concurrency + cache hit rate |
| Query latency | retrieval-service replicas + Redis cache + Neo4j read replicas |
| Tenant isolation under load | partitions keyed by org_id; hot tenants get more partitions |

Everything horizontal-scales by adding partitions and replicas; there is no single-writer bottleneck except per store, and those stores cluster.

## Cloud portability

`infra/terraform/` is laid out to target AWS, GCP, or Azure by swapping the provider module: managed Kafka (MSK / Confluent / Event Hubs), managed Postgres, managed Redis, Neo4j Aura or self-hosted, Qdrant Cloud or self-hosted. Because services talk to infrastructure only through the `platform` package's clients, moving from self-hosted to managed is a config change, not a code change. Modal handles GPU workers independent of the primary cloud. Railway/Fly.io are supported for a small single-region deployment via the same container images.

## Health, readiness, and failure

Every service exposes `/health` (liveness) and `/ready` (readiness — checks its store and Kafka connectivity) so Kubernetes can gate traffic and restarts. Dead-letter topics per stage capture poison messages for inspection without blocking partitions. Grafana alert rules (in `infra/grafana/`) fire on consumer lag growth, DLQ arrivals, error-rate spikes, and store unavailability. The runbook for each alert links back to the relevant service README.
