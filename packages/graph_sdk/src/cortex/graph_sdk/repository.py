"""GraphRepository port.

Every method requires org_id: there is no unscoped query path, so tenant isolation is
enforced in the type system (ADR-0008). Writers (upsert_*) are only called by
graph-service; all other services use the read methods.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from cortex.contracts.enums import EdgeType, NodeLabel
from cortex.graph_sdk.models import Edge, Node


class GraphRepository(ABC):
    # --- writes (graph-service only) ---
    @abstractmethod
    def upsert_node(
        self, *, org_id: str, label: NodeLabel, natural_key: str, source: str,
        properties: dict, provenance_event_id: str, confidence: float = 1.0,
    ) -> Node:
        """Idempotent MERGE by (org_id, natural_key). Returns the resulting node."""

    @abstractmethod
    def upsert_edge(
        self, *, org_id: str, type: EdgeType, from_id: str, to_id: str,
        confidence: float, discovered_by: str, provenance_event_id: str,
        properties: dict | None = None,
    ) -> Edge:
        """Idempotent MERGE of a current edge between two nodes."""

    @abstractmethod
    def close_edge(self, *, org_id: str, edge_id: str) -> None:
        """Close an edge (set valid_to=now) instead of deleting it."""

    @abstractmethod
    def set_urgency(
        self, *, org_id: str, node_id: str, score: float, features: dict[str, float]
    ) -> None: ...

    # --- reads (everyone) ---
    @abstractmethod
    def get_node(self, *, org_id: str, node_id: str) -> Node | None: ...

    @abstractmethod
    def find_node(self, *, org_id: str, natural_key: str) -> Node | None: ...

    @abstractmethod
    def neighborhood(
        self, *, org_id: str, node_id: str, hops: int = 2,
        edge_types: list[EdgeType] | None = None, current_only: bool = True,
    ) -> tuple[list[Node], list[Edge]]:
        """k-hop subgraph around a node. The unit of context for scoring and reasoning."""

    @abstractmethod
    def edges_of(self, *, org_id: str, node_id: str, current_only: bool = True) -> list[Edge]: ...

    @abstractmethod
    def top_by_urgency(self, *, org_id: str, limit: int = 20, min_score: float = 0.0) -> list[Node]: ...

    @abstractmethod
    def all_nodes(self, *, org_id: str) -> list[Node]: ...
