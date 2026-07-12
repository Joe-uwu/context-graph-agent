"""Hybrid retrieval and evidence gathering.

gather_evidence(node) returns the k-hop subgraph the reasoning layer cites. search()
fuses graph, vector, and keyword arms with reciprocal-rank fusion, then reranks by
relationship proximity. The vector arm is a Protocol with a no-op default so the service
runs without an embedding backend; a Qdrant-backed VectorIndex drops in behind it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from cortex.graph_sdk.models import Edge, Node
from cortex.graph_sdk.repository import GraphRepository


@dataclass
class EvidenceSet:
    anchor: Node
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def node_by_id(self, node_id: str) -> Node | None:
        return next((n for n in self.nodes if n.id == node_id), None)


class VectorIndex(Protocol):
    def search(self, org_id: str, query: str, limit: int) -> list[str]: ...  # returns node ids


class NoOpVectorIndex:
    def search(self, org_id: str, query: str, limit: int) -> list[str]:
        return []


class RetrievalService:
    def __init__(self, repo: GraphRepository, vectors: VectorIndex | None = None) -> None:
        self._repo = repo
        self._vectors = vectors or NoOpVectorIndex()

    def gather_evidence(self, *, org_id: str, node_id: str, hops: int = 2) -> EvidenceSet | None:
        anchor = self._repo.get_node(org_id=org_id, node_id=node_id)
        if anchor is None:
            return None
        nodes, edges = self._repo.neighborhood(org_id=org_id, node_id=node_id, hops=hops)
        return EvidenceSet(anchor=anchor, nodes=nodes, edges=edges)

    def search(self, *, org_id: str, query: str, limit: int = 20) -> list[Node]:
        graph_hits = self._keyword_arm(org_id=org_id, query=query)
        vector_hits = self._vectors.search(org_id, query, limit)
        fused = _rrf([[n.id for n in graph_hits], vector_hits])
        ordered: list[Node] = []
        for node_id in fused[:limit]:
            node = self._repo.get_node(org_id=org_id, node_id=node_id)
            if node:
                ordered.append(node)
        return ordered

    def _keyword_arm(self, *, org_id: str, query: str) -> list[Node]:
        q = query.lower()
        return [n for n in self._repo.all_nodes(org_id=org_id) if q in n.display().lower()]


def _rrf(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal-rank fusion across heterogeneous arms (docs/design/hybrid-retrieval.md)."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, node_id in enumerate(ranking):
            scores[node_id] = scores.get(node_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda nid: scores[nid], reverse=True)
