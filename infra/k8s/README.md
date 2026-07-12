# Kubernetes manifests

Each service is a Deployment plus a HorizontalPodAutoscaler scaled on its own signal
(see `docs/architecture/services.md`). Namespaces mirror the tiers in
`docs/architecture/architecture.md`: `edge`, `processing`, `ingestion`, `data`.

`graph-service.yaml` is the reference manifest; the other services follow the same shape
with a different command, env, and scale signal. In a real repo these are generated from
a Helm chart or Kustomize base with per-service overlays; the single manifest here shows
the pattern without duplicating it eight times.

```
kubectl apply -k infra/k8s        # once the base + overlays are filled in
```

Backing stores (Kafka via Strimzi, Neo4j causal cluster, Qdrant, Redis, Postgres) are run
by their respective operators in the `data` namespace, not by these manifests.
