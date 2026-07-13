# Observability

Every Cortex service emits the three pillars, and the stack ships the collectors and
dashboards to read them.

## Pillars

- **Metrics** — each service exposes Prometheus metrics at `/metrics` (see
  `cortex.platform.observability`). Prometheus scrapes all eight plus kafka-exporter and the
  OTel collector.
- **Traces** — services export OTLP spans to the OTel collector (`CORTEX_OTEL_ENDPOINT`).
  The collector forwards them to Tempo and derives service-graph + span metrics.
- **Logs** — structured JSON to stdout, carrying `trace_id` so a log line links to its trace
  (`cortex.platform.logging`).

## What's exposed

| Metric | Meaning |
| --- | --- |
| `cortex_http_requests_total{service,method,path,status}` | throughput + error rate (5xx) |
| `cortex_http_request_duration_seconds_bucket{service,le}` | latency (p50/p95/p99 via `histogram_quantile`) |
| `cortex_http_requests_in_flight{service}` | concurrency |
| `cortex_events_processed_total{service}` | pipeline throughput per stage |
| `cortex_events_published_total{source}` | ingestion rate per source |
| `cortex_risk_score{service}` (histogram) | urgency score distribution |
| `cortex_notifications_sent_total{channel}` | alerts routed |
| `cortex_github_*` | connector requests/retries/rate-limit/webhooks |
| `kafka_consumergroup_lag{consumergroup,topic}` | **Kafka lag** (kafka-exporter) |
| `traces_service_graph_request_total{client,server}` | **service map** edges (from traces) |

## Where to look (`make up`)

- **Grafana** — http://localhost:3001 (anonymous). Two provisioned dashboards under the
  *Cortex* folder:
  - *Platform Overview* — throughput, p95 latency, error ratio, in-flight (RED metrics).
  - *Pipeline & Kafka* — events/sec per stage, events by source, Kafka consumer lag,
    notifications by channel, risk-score p50/p95, and inter-service call rate.
- **Service map** — Grafana → Explore → Tempo → *Service Graph* (built from the collector's
  servicegraph metrics in Prometheus).
- **Prometheus** — http://localhost:9090 (targets, rules, ad-hoc PromQL).
- **Traces** — Grafana → Explore → Tempo.

## Recording rules & alerts

`infra/monitoring/prometheus/alerts/cortex.rules.yml` precomputes per-service request rate,
error ratio, and latency quantiles, and defines alerts:

- `CortexServiceDown` — a service is unscrapeable for 1m.
- `CortexHighErrorRate` — 5xx ratio > 5% for 5m.
- `CortexHighLatencyP95` — p95 > 1s for 10m.
- `CortexKafkaConsumerLag` — a consumer group > 1000 messages behind for 10m.
- `CortexPipelineStalled` — events ingested but none processed for 10m.

## Adding a metric

Call `METRICS.inc/gauge/observe(...)` (labels are keyword args) anywhere in a service; it is
exposed at `/metrics` automatically and scraped within 15s. Register a HELP/TYPE with
`METRICS.register(name, kind, help)` for nicer output.
