# 0003 — Connector framework with real + mock twins

Status: Accepted

## Context

Six sources (GitHub, Slack, Jira, Notion, Calendar, PagerDuty), each with its own API, auth, pagination, rate limits, and change-notification mechanism. Two problems: the per-source code will diverge into six bespoke integrations unless constrained, and the platform must be demonstrable end-to-end without live enterprise accounts or credentials.

## Decision

Define one connector interface — `initial_sync`, `incremental_sync`, `stream`, plus `normalize` — with shared machinery for pagination, rate limiting (Redis token bucket), retry (exponential backoff + jitter), deduplication (by source delivery id), and cursor persistence (Postgres). Every source ships two implementations behind that interface: a real connector and a mock connector backed by a synthetic event generator that produces realistic, cross-source-consistent event streams (the same incident referenced in Slack, Jira, and PagerDuty). Which one runs is configuration.

## Consequences

Adding a source means implementing one interface, not reinventing sync logic. The synthetic twin lets the whole pipeline run in CI and in demos with no secrets, and lets us generate the pathological scenarios (a deploy blocked by a cross-source chain) on demand for testing. Switching a demo org to real data is a credential and config change, not a code change. The cost is keeping the mock generator realistic enough to be useful, and maintaining two implementations per source; the mock is cheap because it only has to satisfy the same normalize step.

## Alternatives considered

Real connectors only, tested against recorded fixtures — rejected because it cannot generate novel cross-source scenarios and makes local/demo runs depend on live accounts. A third-party ingestion product (Airbyte, Fivetran) — rejected because those target warehouse ETL, not low-latency event streaming with per-record normalization into a typed envelope.
