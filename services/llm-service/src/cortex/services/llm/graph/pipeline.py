"""Wire the nine nodes into the reasoning graph and adapt it to the Reasoner protocol.

Graph shape:

    observe -> retrieve -> verify --(verified)--> graph_traverse -> reason -> ground
                                  \--(not verified)--> END
    ... -> explain -> recommend -> notify -> END

GraphReasoner runs the graph and assembles a ReasoningProduced, so it drops into the
existing llm-service worker/http in place of TemplateReasoner.
"""

from __future__ import annotations

from dataclasses import dataclass

from cortex.contracts.payloads import ReasoningProduced
from cortex.platform.logging import get_logger
from cortex.services.llm.graph import nodes as N
from cortex.services.llm.graph.engine import END, StateGraph
from cortex.services.llm.graph.state import ReasoningState
from cortex.services.retrieval.service import EvidenceSet, RetrievalService

log = get_logger("cortex.llm.graph")


@dataclass
class ReasoningConfig:
    retrieval: RetrievalService | None = None
    evidence_hops: int = 3
    max_clauses: int = 6
    interrupt_at: float = 0.75
    node_retries: int = 2
    # Optional OpenAI-compatible LlmClient; when set, the Reason node uses it (duck-typed to
    # avoid a hard import). None → deterministic template reasoning.
    llm: object | None = None


def build_reasoning_graph(*, node_retries: int = 2) -> StateGraph:
    graph = StateGraph()
    graph.add_node("observe", N.observe, retries=node_retries)
    graph.add_node("retrieve", N.retrieve, retries=node_retries)
    graph.add_node("verify", N.verify, retries=node_retries)
    graph.add_node("graph_traverse", N.graph_traverse, retries=node_retries)
    graph.add_node("reason", N.reason, retries=node_retries)
    graph.add_node("ground", N.ground, retries=node_retries)
    graph.add_node("explain", N.explain, retries=node_retries)
    graph.add_node("recommend", N.recommend, retries=node_retries)
    graph.add_node("notify", N.notify, retries=node_retries)

    graph.set_entry("observe")
    graph.add_edge("observe", "retrieve")
    graph.add_edge("retrieve", "verify")
    graph.add_conditional("verify", lambda s: s.verified, "graph_traverse", END)
    graph.add_edge("graph_traverse", "reason")
    graph.add_edge("reason", "ground")
    graph.add_edge("ground", "explain")
    graph.add_edge("explain", "recommend")
    graph.add_edge("recommend", "notify")
    graph.add_edge("notify", END)
    return graph


def _assemble(state: ReasoningState) -> ReasoningProduced:
    summary = state.summary or f"Node {state.node_id} risk {state.risk_score:.2f}"
    explanation = state.narrative or state.explanation or summary
    if state.halted and not state.explanation:
        explanation = f"{summary} (reasoning halted: {state.halt_reason})"
    return ReasoningProduced(
        node_id=state.node_id,
        summary=summary,
        explanation=explanation,
        actions=state.actions,
        citations=state.citations,
        confidence=state.confidence,
        risk_score=state.risk_score,
    )


class GraphReasoner:
    """Reasoner backed by the reasoning graph (implements the Reasoner protocol)."""

    def __init__(self, config: ReasoningConfig | None = None) -> None:
        self._config = config or ReasoningConfig()
        self._graph = build_reasoning_graph(node_retries=self._config.node_retries)

    def reason(self, evidence: EvidenceSet, risk_score: float) -> ReasoningProduced:
        state = ReasoningState(
            org_id=evidence.anchor.org_id,
            node_id=evidence.anchor.id,
            risk_score=risk_score,
            evidence=evidence,
        )
        final = self._graph.run(state, self._config)
        return _assemble(final)

    def run_from_trigger(self, *, org_id: str, node_id: str, risk_score: float) -> ReasoningState:
        """Run the whole graph from a bare trigger (Observe + Retrieve included). Requires a
        retrieval service in the config."""
        state = ReasoningState(org_id=org_id, node_id=node_id, risk_score=risk_score)
        return self._graph.run(state, self._config)


def build_reasoner(settings, *, retrieval: RetrievalService | None = None):
    """Build the graph reasoner from settings. ``llm_provider == "openai"`` plugs a real
    OpenAI-compatible model into the Reason node; otherwise the deterministic template runs."""
    llm = None
    if getattr(settings, "llm_provider", "template") == "openai":
        from cortex.services.llm.llm_client import LlmClient

        llm = LlmClient(
            model=getattr(settings, "llm_model", "gpt-4o-mini"),
            api_key=getattr(settings, "llm_api_key", ""),
            base_url=getattr(settings, "llm_base_url", "https://api.openai.com/v1"),
        )
    config = ReasoningConfig(
        retrieval=retrieval,
        evidence_hops=getattr(settings, "evidence_hops", 3),
        llm=llm,
    )
    engine = getattr(settings, "reasoner_engine", "native")
    if engine == "langgraph":
        from cortex.services.llm.graph.langgraph_pipeline import (
            LangGraphReasoner,
            langgraph_available,
        )
        if langgraph_available():
            log.info("reasoner engine: langgraph")
            return LangGraphReasoner(config)
        log.warning("reasoner_engine=langgraph but langgraph is not installed; "
                    "falling back to the native engine")
    return GraphReasoner(config)
