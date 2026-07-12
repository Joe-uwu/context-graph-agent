# 0011 — Ray for distributed background ranking

Status: Accepted

## Context

Ranking recomputes urgency over the subgraph around every changed node, continuously. A burst (a large PR merge, an incident storm) can touch many nodes at once, each needing a k-hop extraction and a feature computation. This is embarrassingly parallel and spiky: idle much of the time, then a flood. It also occasionally needs GPU (the optional GNN scorer).

## Decision

Run ranking as Ray jobs. A driver consumes `graph.changes`, coalesces bursts into a changed-node set, and fans per-subgraph scoring across Ray workers; results are written back to Neo4j and threshold-crossers emit `risk.scored`. Ray runs in local mode for development and as a cluster in production, with GPU workers for the optional GNN path. CPU feature scoring and GPU inference share the same scheduling substrate.

## Consequences

Parallel scoring scales horizontally with the burst, then scales back when idle, so freshness holds under churn without permanently provisioning for peak. One framework covers CPU fan-out and GPU inference, avoiding a second system. Local mode keeps development identical to production in shape. The costs: Ray is another runtime to operate and reason about, and its failure modes (object store pressure, worker loss) need monitoring; for very small deployments Ray is heavier than a simple worker pool, which is why local mode exists as the low-overhead path.

## Alternatives considered

Celery workers — already used for connector scheduling and simpler, but weaker for dynamic fan-out of many short parallel tasks and no natural GPU story. A serverless fan-out (Lambda/Cloud Run jobs) — viable for the CPU path but adds latency per invocation and complicates the GPU/GNN path and local dev. Doing ranking inline in `graph-service` — rejected: it would couple write throughput to scoring cost and cannot absorb bursts without backing up the graph writer.
