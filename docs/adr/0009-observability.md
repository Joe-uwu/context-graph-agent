# 0009 — Observability with OpenTelemetry, Prometheus, Grafana

Status: Accepted

## Context

An event crosses six or more services between a source webhook and a delivered notification, asynchronously, across Kafka. When a notification is wrong, late, or missing, "which stage" is the first question, and without distributed tracing it is unanswerable. The system also needs to know queue depths and per-stage latency to scale correctly.

## Decision

Instrument every service with OpenTelemetry. The `trace_id` is created at ingestion and carried unchanged in the event envelope through every stage, so one trace spans source event to delivered notification even across Kafka hops. Export RED metrics (rate, errors, duration) per service and per Kafka topic (including consumer lag / queue depth) to Prometheus. Dashboards and alerts in Grafana. Logs are structured JSON carrying the `trace_id` so a log line links back to its trace. Health (`/health`, `/ready`) and metrics (`/metrics`) endpoints on every service.

## Consequences

A misbehaving pipeline is diagnosable end-to-end: pick the trace, see where time went or where it failed. Consumer-lag metrics drive scaling decisions per stage. Structured logs correlate to traces without guesswork. The cost is instrumentation discipline (the `platform` package centralizes it so services get it nearly for free) and the overhead of running the collector/Prometheus/Grafana stack, which is standard.

## Alternatives considered

Per-service ad hoc logging with no trace propagation — rejected; async multi-hop flows are undebuggable without a shared trace id. A single vendor APM — viable, but OTel keeps the instrumentation vendor-neutral so the backend can change without re-instrumenting. Metrics without tracing — insufficient, because metrics tell you a stage is slow but not why a specific event went wrong.
