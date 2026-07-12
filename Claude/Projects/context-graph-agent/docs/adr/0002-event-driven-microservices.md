# 0002 — Event-driven microservices over Kafka

Status: Accepted

## Context

The pipeline has stages with very different throughput and latency profiles. Ingestion is bursty and cheap; LLM reasoning is slow and expensive. Ranking must run continuously in the background. If these were chained synchronously, the slowest stage would set the pace for all of them, a failure in one would fail the request end-to-end, and scaling would mean scaling everything together.

## Decision

Structure the platform as independently deployable services joined by a Kafka event bus. Each service consumes a topic, does its work, and produces to the next. No service calls the next stage synchronously across the pipeline. Topics are partitioned by `org_id`. Delivery is at-least-once with offsets committed only after a successful downstream produce; consumers are idempotent. Poison messages route to a per-topic dead-letter topic after bounded retries.

## Consequences

Each stage scales on its own signal (ingestion on event rate, reasoning on backlog). A slow or failing stage queues work instead of failing the source. Every mutation is an event, which gives replay, audit, and a natural place to attach tracing. The costs are real: eventual consistency (a graph change takes time to become a notification), the operational weight of running Kafka, and the need for idempotency everywhere. We accept these because the alternative does not meet the "thousands of events/minute, sub-second graph queries, background ranking" requirement.

## Alternatives considered

A synchronous request/response monolith or service mesh — simpler to run, but couples throughput across stages and cannot do continuous background ranking naturally. A task queue (Celery/RQ) instead of a log — rejected as the backbone because a queue consumes messages destructively, losing replay and multi-consumer fan-out; Celery is still used, but only for scheduling connector syncs. A cloud-managed bus (SQS/PubSub) — viable, and the connector wrapper keeps that swap cheap, but Kafka's partitioned log with consumer groups and long retention matches the replay/ordering needs directly.
