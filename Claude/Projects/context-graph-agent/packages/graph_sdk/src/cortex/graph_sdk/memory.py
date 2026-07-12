"""In-memory GraphRepository.

Backs local dev, the demo, and tests. Semantics match the Neo4j implementation:
idempotent upsert by (org_id, natural_key), edges closed rather than deleted, k-hop
traversal over current edges. Not persistent and not concurrent — the production path
is Neo4jGraphRepository.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone

from cortex.contracts.enums import DiscoveredBy, EdgeType, NodeLabel
from cortex.graph_sdk.models import Edge, Node
from cortex.graph_sdk.repository import GraphRepository
from cortex.platform.ids import new_id


class InMemoryGraphRepository(GraphRepository):
    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}
        self._by_key: dict[tuple[str, str], str] = {}
        self._out: dict[str, set[str]] = defaultdict(set)
        self._in: dict[str, set[str]] = defaultdict(set)

    def upsert_node(
        self, *, org_id, label: NodeLabel, natural_key, source,
        properties, provenance_event_id, confidence=1.0,
    ) -> Node:
        key = (org_id, natural_key)
        existing_id = self._by_key.get(key)
        if existing_id:
            node = self._nodes[existing_id]
            node.properties.update(properties)
            if provenance_event_id not in node.provenance:
                node.provenance.append(provenance_event_id)
            node.confidence = max(node.confidence, confidence)
            node.updated_at = datetime.now(timezone.utc)
            return node
        node = Node(
            id=new_id("nd"), org_id=org_id, label=label, natural_key=natural_key,
            source=source, properties=dict(properties), provenance=[provenance_event_id],
            confidence=confidence,
        )
        self._nodes[node.id] = node
        self._by_key[key] = node.id
        return node

    def upsert_edge(
        self, *, org_id, type: EdgeType, from_id, to_id, confidence,
        discovered_by, provenance_event_id, properties=None,
    ) -> Edge:
        for eid in self._out.get(from_id, set()):
            e = self._edges[eid]
            if e.type == type and e.to_id == to_id and e.is_current:
                if provenance_event_id not in e.provenance:
                    e.provenance.append(provenance_event_id)
                e.confidence = max(e.confidence, confidence)
                return e
        edge = Edge(
            id=new_id("eg"), org_id=org_id, type=type, from_id=from_id, to_id=to_id,
            confidence=confidence, discovered_by=DiscoveredBy(discovered_by),
            provenance=[provenance_event_id], properties=dict(properties or {}),
        )
        self._edges[edge.id] = edge
        self._out[from_id].add(edge.id)
        self._in[to_id].add(edge.id)
        return edge

    def close_edge(self, *, org_id, edge_id) -> None:
        edge = self._edges.get(edge_id)
        if edge and edge.org_id == org_id and edge.is_current:
            edge.valid_to = datetime.now(timezone.utc)

    def set_urgency(self, *, org_id, node_id, score, features) -> None:
        node = self._nodes.get(node_id)
        if node and node.org_id == org_id:
            node.urgency = score
            node.urgency_features = dict(features)

    def get_node(self, *, org_id, node_id) -> Node | None:
        node = self._nodes.get(node_id)
        return node if node and node.org_id == org_id else None

    def find_node(self, *, org_id, natural_key) -> Node | None:
        nid = self._by_key.get((org_id, natural_key))
        return self._nodes.get(nid) if nid else None

    def edges_of(self, *, org_id, node_id, current_only=True) -> list[Edge]:
        ids = self._out.get(node_id, set()) | self._in.get(node_id, set())
        edges = [self._edges[i] for i in ids]
        edges = [e for e in edges if e.org_id == org_id]
        return [e for e in edges if e.is_current] if current_only else edges

    def neighborhood(
        self, *, org_id, node_id, hops=2, edge_types=None, current_only=True,
    ) -> tuple[list[Node], list[Edge]]:
        allowed = set(edge_types) if edge_types else None
        seen_nodes: dict[str, Node] = {}
        seen_edges: dict[str, Edge] = {}
        start = self.get_node(org_id=org_id, node_id=node_id)
        if not start:
            return [], []
        seen_nodes[start.id] = start
        frontier: deque[tuple[str, int]] = deque([(node_id, 0)])
        while frontier:
            current, depth = frontier.popleft()
            if depth >= hops:
                continue
            for edge in self.edges_of(org_id=org_id, node_id=current, current_only=current_only):
                if allowed is not None and edge.type not in allowed:
                    continue
                seen_edges[edge.id] = edge
                other = edge.to_id if edge.from_id == current else edge.from_id
                if other not in seen_nodes:
                    node = self._nodes.get(other)
                    if node and node.org_id == org_id:
                        seen_nodes[other] = node
                        frontier.append((other, depth + 1))
        return list(seen_nodes.values()), list(seen_edges.values())

    def top_by_urgency(self, *, org_id, limit=20, min_score=0.0) -> list[Node]:
        nodes = [n for n in self._nodes.values() if n.org_id == org_id and n.urgency >= min_score]
        nodes.sort(key=lambda n: n.urgency, reverse=True)
        return nodes[:limit]

    def all_nodes(self, *, org_id) -> list[Node]:
        return [n for n in self._nodes.values() if n.org_id == org_id]
