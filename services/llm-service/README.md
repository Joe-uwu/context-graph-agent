# llm-service

Consumes `risk.scored`, gathers k-hop evidence via retrieval-service, runs the grounded
reasoning graph, and emits `reasoning.produced`. Serves on-demand reasoning over HTTP.

## Topics

- Consumes: `risk.scored`
- Produces: `reasoning.produced`

## Reasoning graph

The reasoning stage is a typed state graph (`cortex.services.llm.graph`), not a single
prompt→answer call:

    Observe → Retrieve → Verify → GraphTraverse → Reason → Ground → Explain → Recommend → Notify

Each node is a pure, independently-callable function over a typed `ReasoningState`; the
engine runs them with per-node retry and records a trace, and `Verify` can halt the pipeline
when the evidence is too thin to reason over. `Ground` runs the citation validator, so every
claim resolves to a real graph node or edge (confidence = the weakest cited edge). `Reason`,
`Explain`, and `Recommend` build the text; a real LangGraph/LLM backend can replace the node
bodies without changing the graph shape (`langgraph` optional extra). `GraphReasoner`
implements the `Reasoner` protocol, so it drops straight into the worker and the HTTP route.

## HTTP surface

Port `8006` (override with `CORTEX_HTTP_PORT`). `/api/v1/reason` is org-scoped via `X-Org-Id`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` `/ready` `/metrics` | Ops |
| POST | `/api/v1/reason` | Reason over a node's evidence (`{node_id, hops?, risk_score?}`) |

The response is a `ReasoningProduced` payload: summary, explanation, recommended actions,
and citations that point back to graph nodes/edges.

## Configuration

`CORTEX_RUNTIME`, `CORTEX_NEO4J_*`, `CORTEX_EVIDENCE_HOPS` (default `3`), `CORTEX_HTTP_PORT`
(default `8006`), `CORTEX_OTEL_ENDPOINT`.

## Run

```bash
CORTEX_HTTP_PORT=8006 python -m cortex.services.llm.main
docker build -f services/llm-service/Dockerfile -t cortex/llm-service .
docker run -p 8006:8006 cortex/llm-service
```

## Metrics

`cortex_events_processed_total{service="llm-service"}`, plus the shared HTTP metrics.

## Tests

```bash
pytest tests/services/test_llm_service.py
```
