"""A small typed state-graph engine.

Nodes are named callables ``(state, deps) -> state``; edges connect them, optionally on a
condition. The runner executes from the entry node, retries a failing node up to its retry
budget, records a trace, and stops at END or when a node sets ``state.halted``. This is the
same shape as LangGraph (typed state, nodes, conditional edges, retries) with no external
dependency, so the pipeline runs and is testable offline.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from cortex.platform.logging import get_logger

log = get_logger("cortex.llm.graph")

END = "__end__"

NodeFn = Callable[[Any, Any], Any]
Condition = Callable[[Any], bool]


@dataclass
class Node:
    name: str
    fn: NodeFn
    retries: int = 1  # total attempts

    def run(self, state: Any, deps: Any) -> Any:
        return self.fn(state, deps)


@dataclass
class _Edge:
    condition: Condition | None
    if_true: str
    if_false: str | None = None


@dataclass
class StateGraph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, _Edge] = field(default_factory=dict)
    entry: str | None = None

    def add_node(self, name: str, fn: NodeFn, *, retries: int = 1) -> "StateGraph":
        if name in self.nodes:
            raise ValueError(f"duplicate node: {name}")
        self.nodes[name] = Node(name, fn, retries=retries)
        return self

    def set_entry(self, name: str) -> "StateGraph":
        self.entry = name
        return self

    def add_edge(self, frm: str, to: str) -> "StateGraph":
        self.edges[frm] = _Edge(condition=None, if_true=to)
        return self

    def add_conditional(self, frm: str, condition: Condition, if_true: str, if_false: str) -> "StateGraph":
        self.edges[frm] = _Edge(condition=condition, if_true=if_true, if_false=if_false)
        return self

    def _next(self, current: str, state: Any) -> str:
        edge = self.edges.get(current)
        if edge is None:
            return END
        if edge.condition is None:
            return edge.if_true
        return edge.if_true if edge.condition(state) else (edge.if_false or END)

    def run(self, state: Any, deps: Any = None, *, max_steps: int = 100) -> Any:
        if self.entry is None:
            raise ValueError("no entry node set")
        current = self.entry
        steps = 0
        while current != END and steps < max_steps:
            steps += 1
            node = self.nodes[current]
            state = self._run_node(node, state, deps)
            state.trace.append(node.name)
            if getattr(state, "halted", False):
                break
            current = self._next(current, state)
        return state

    @staticmethod
    def _run_node(node: Node, state: Any, deps: Any) -> Any:
        last: Exception | None = None
        for attempt in range(1, node.retries + 1):
            try:
                return node.run(state, deps)
            except Exception as exc:  # noqa: BLE001 - a node error is recoverable via retry
                last = exc
                log.warning(
                    "reasoning node failed",
                    extra={"extra_fields": {"node": node.name, "attempt": attempt, "error": str(exc)}},
                )
        # Retries exhausted: halt the pipeline rather than crash the worker.
        state.trace.append(f"{node.name}:error")
        return state.halt(f"node '{node.name}' failed: {last}")
