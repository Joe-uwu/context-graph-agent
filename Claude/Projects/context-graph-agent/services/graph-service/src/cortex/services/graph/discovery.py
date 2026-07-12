"""Relationship discovery — three tiers in cost order (ADR: architecture doc).

Tier 1 (rule): edges the extractor already asserted from source structure/text.
Tier 2 (embedding): fuzzy links by node-embedding similarity above a threshold.
Tier 3 (llm): the residue the first two cannot decide, at capped confidence.

Only tier 1 is fully wired in the reference build (it covers the demo scenario). Tiers 2
and 3 are interfaces with deterministic no-op defaults so the pipeline runs without an
embedding model or LLM; a real EmbeddingSimilarity / LlmLinker drops in behind them.
"""

from __future__ import annotations

from typing import Protocol

from cortex.contracts.payloads import ExtractedEdge, ExtractedNode


class EmbeddingSimilarity(Protocol):
    def candidate_edges(
        self, nodes: list[ExtractedNode]
    ) -> list[ExtractedEdge]: ...


class LlmLinker(Protocol):
    def residual_edges(
        self, nodes: list[ExtractedNode], existing: list[ExtractedEdge]
    ) -> list[ExtractedEdge]: ...


class NoOpSimilarity:
    def candidate_edges(self, nodes: list[ExtractedNode]) -> list[ExtractedEdge]:
        return []


class NoOpLinker:
    def residual_edges(
        self, nodes: list[ExtractedNode], existing: list[ExtractedEdge]
    ) -> list[ExtractedEdge]:
        return []


class RelationshipDiscovery:
    def __init__(
        self,
        similarity: EmbeddingSimilarity | None = None,
        linker: LlmLinker | None = None,
    ) -> None:
        self._similarity = similarity or NoOpSimilarity()
        self._linker = linker or NoOpLinker()

    def discover(
        self, nodes: list[ExtractedNode], rule_edges: list[ExtractedEdge]
    ) -> list[ExtractedEdge]:
        edges = list(rule_edges)
        edges.extend(self._similarity.candidate_edges(nodes))
        edges.extend(self._linker.residual_edges(nodes, edges))
        return edges
