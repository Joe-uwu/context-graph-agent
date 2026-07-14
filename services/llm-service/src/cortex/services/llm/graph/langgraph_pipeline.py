"""LangGraph-backed reasoning pipeline.

The same nine node functions used by the native engine (graph/nodes.py) are assembled here
with the actual ``langgraph`` library's ``StateGraph`` instead of the hand-rolled engine. The
dataclass ``ReasoningState`` rides in a single state channel ("rs"), so the node functions are
reused verbatim and the LLM plug-in (deps.llm) plus the Ground validator behave identically.

``LangGraphReasoner`` implements the same Reasoner protocol as ``GraphReasoner``; the config
factory (graph/pipeline.build_reasoner) selects it when ``reasoner_engine="langgraph"`` and the
library is importable, otherwise the native engine runs. Importing langgraph is deferred into
the builder so the package stays importable without the dependency.
"""

from __future__ import annotations

from typing import TypedDict

from cortex.contracts.payloads import ReasoningProduced
from cortex.services.llm.graph import nodes as N
from cortex.services.llm.graph.pipeline import ReasoningConfig, _assemble
from cortex.services.llm.graph.state import ReasoningState
from cortex.services.retrieval.service import EvidenceSet

_NODES = [
    ("observe", N.observe),
    ("retrieve", N.retrieve),
    ("verify", N.verify),
    ("graph_traverse", N.graph_traverse),
    ("reason", N.reason),
    ("ground", N.ground),
    ("explain", N.explain),
    ("recommend", N.recommend),
    ("notify", N.notify),
]


class _GraphState(TypedDict):
    rs: ReasoningState


def _wrap(fn, deps):
    """Adapt a (state, deps) node to a LangGraph node over the single 'rs' channel."""

    def node(state: _GraphState) -> dict:
        return {"rs": fn(state["rs"], deps)}

    return node


def langgraph_available() -> bool:
    try:
        import langgraph.graph  # noqa: F401
    except Exception:
        return False
    return True


def build_langgraph_app(config: ReasoningConfig):
    """Compile the nine-node reasoning graph on the langgraph runtime.

    verify routes to graph_traverse when the evidence is corroborated, else straight to END —
    the same conditional the native engine uses.
    """
    from langgraph.graph import END, StateGraph

    graph = StateGraph(_GraphState)
    for name, fn in _NODES:
        graph.add_node(name, _wrap(fn, config))

    graph.set_entry_point("observe")
    graph.add_edge("observe", "retrieve")
    graph.add_edge("retrieve", "verify")
    graph.add_conditional_edges(
        "verify",
        lambda s: "graph_traverse" if s["rs"].verified else END,
    )
    graph.add_edge("graph_traverse", "reason")
    graph.add_edge("reason", "ground")
    graph.add_edge("ground", "explain")
    graph.add_edge("explain", "recommend")
    graph.add_edge("recommend", "notify")
    graph.add_edge("notify", END)
    return graph.compile()


class LangGraphReasoner:
    """Reasoner backed by the langgraph runtime (implements the Reasoner protocol)."""

    def __init__(self, config: ReasoningConfig | None = None) -> None:
        self._config = config or ReasoningConfig()
        self._app = build_langgraph_app(self._config)

    def reason(self, evidence: EvidenceSet, risk_score: float) -> ReasoningProduced:
        state = ReasoningState(
            org_id=evidence.anchor.org_id,
            node_id=evidence.anchor.id,
            risk_score=risk_score,
            evidence=evidence,
        )
        out = self._app.invoke({"rs": state})
        return _assemble(out["rs"])

    def run_from_trigger(self, *, org_id: str, node_id: str, risk_score: float) -> ReasoningState:
        state = ReasoningState(org_id=org_id, node_id=node_id, risk_score=risk_score)
        return self._app.invoke({"rs": state})["rs"]
