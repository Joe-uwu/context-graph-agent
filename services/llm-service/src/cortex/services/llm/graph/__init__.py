"""LangGraph-style reasoning pipeline for llm-service.

The reasoning stage is a typed state graph, not a single prompt→answer call:

    Observe → Retrieve → Verify → GraphTraverse → Reason → Ground → Explain → Recommend → Notify

Each node is a pure, independently-callable function over a typed ReasoningState; the engine
runs them with per-node retry and records a trace. GraphReasoner adapts the pipeline to the
Reasoner protocol so it drops into the existing worker. A real LangGraph/LLM backend can
replace the node bodies without changing the graph shape.
"""

from cortex.services.llm.graph.engine import END, Node, StateGraph
from cortex.services.llm.graph.pipeline import (
    GraphReasoner,
    ReasoningConfig,
    build_reasoner,
    build_reasoning_graph,
)
from cortex.services.llm.graph.langgraph_pipeline import (
    LangGraphReasoner,
    build_langgraph_app,
    langgraph_available,
)
from cortex.services.llm.graph.state import Finding, ReasoningState

__all__ = [
    "END",
    "Node",
    "StateGraph",
    "GraphReasoner",
    "ReasoningConfig",
    "build_reasoner",
    "LangGraphReasoner",
    "build_langgraph_app",
    "langgraph_available",
    "build_reasoning_graph",
    "ReasoningState",
    "Finding",
]
