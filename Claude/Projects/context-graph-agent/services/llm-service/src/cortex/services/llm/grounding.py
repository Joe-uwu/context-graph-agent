"""Grounding validator — the anti-hallucination control (ADR-0007).

Every citation must point at a node or edge present in the evidence set. Claims whose
citations do not resolve are rejected. Reasoning confidence is the minimum confidence of
the resolved citations, so an explanation resting on a low-confidence inferred edge is
surfaced as lower-confidence.
"""

from __future__ import annotations

from cortex.contracts.payloads import Citation
from cortex.services.retrieval.service import EvidenceSet


class GroundingValidator:
    def __init__(self, evidence: EvidenceSet) -> None:
        self._node_ids = {n.id for n in evidence.nodes}
        self._edge_ids = {e.id for e in evidence.edges}
        self._edge_conf = {e.id: e.confidence for e in evidence.edges}
        self._node_conf = {n.id: n.confidence for n in evidence.nodes}

    def resolves(self, citation: Citation) -> bool:
        if citation.kind == "node":
            return citation.ref_id in self._node_ids
        if citation.kind == "edge":
            return citation.ref_id in self._edge_ids
        return False

    def filter(self, citations: list[Citation]) -> list[Citation]:
        """Keep only citations that resolve to real evidence."""
        return [c for c in citations if self.resolves(c)]

    def confidence(self, citations: list[Citation]) -> float:
        resolved = self.filter(citations)
        if not resolved:
            return 0.0
        confs = []
        for c in resolved:
            table = self._edge_conf if c.kind == "edge" else self._node_conf
            confs.append(table.get(c.ref_id, 0.0))
        return round(min(confs), 4)
