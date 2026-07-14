# 0007 — Grounded LLM reasoning with LangGraph

Status: Accepted (implemented)

## Context

The reasoning layer produces the human-facing explanation and recommendation. A wrong or fabricated explanation is worse than none: it erodes trust and can send an on-call engineer down the wrong path during an incident. The system must never assert a relationship the graph does not contain. Reasoning is also multi-step (gather evidence, summarize, recommend, validate), not a single prompt.

## Decision

Implement reasoning as a LangGraph state machine with an explicit grounding contract. The model may only reference entities and relationships present in the evidence set that `retrieval-service` returned; every claim in the output must carry a citation to a graph node or edge id. A validation node checks that each claim maps to a citation before the result is emitted, dropping or repairing any claim that does not. Confidence attached to the explanation is inherited from the confidence of the cited edges (see the graph model), not from the model's own stated certainty.

Implementation: the state machine is the nine-node graph Observe → Retrieve → Verify → GraphTraverse → Reason → Ground → Explain → Recommend → Notify. The same node functions run on either a hand-rolled typed-state engine (default) or the real LangGraph runtime (`CORTEX_REASONER_ENGINE=langgraph`), compiled either way. The Reason node calls any OpenAI-compatible chat model (`CORTEX_LLM_PROVIDER=openai`); a deterministic template runs when no model is configured or a call fails. The Ground node is the validator above and gates the output regardless of which engine or model produced it.

## Consequences

Explanations are auditable — every sentence points at graph evidence a user can inspect. Fabricated relationships cannot survive the validator. Confidence is honest because it comes from provenance, not from the model's tone. The costs: reasoning is multi-call and therefore slower and more expensive per item, which is why it runs only above the urgency threshold and behind caching; and the validator can suppress a correct-but-uncited inference, which we accept as the safe failure mode (silence over confident fabrication).

## Alternatives considered

A single summarization prompt with the subgraph in context — simpler and faster, but nothing enforces grounding, so the model can assert links that are not there. Fine-tuning a model on org data — rejected for the MVP: expensive, per-org, and does not by itself guarantee grounding. Pure template-generated explanations from the graph (no LLM) — fully faithful but rigid and poor at synthesizing across a novel evidence shape; the LLM adds fluency, the validator adds the faithfulness the template would have had.
