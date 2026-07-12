"""Reasoner: build a grounded explanation + recommendations from an evidence set.

The Reasoner port is where a real LLM (behind LangGraph) plugs in. TemplateReasoner is
the deterministic, offline default: it walks the evidence subgraph, states only what the
edges assert, and cites every entity and relationship it names. Because it is constructed
from the graph it is grounded by construction; the validator still checks it, which is
what a real LLM's output must also pass.
"""

from __future__ import annotations

from typing import Protocol

from cortex.contracts.enums import EdgeType, NodeLabel
from cortex.contracts.payloads import Citation, ReasoningProduced, RecommendedAction
from cortex.services.llm.grounding import GroundingValidator
from cortex.services.retrieval.service import EvidenceSet

# Which relationships carry the most explanatory weight, most important first.
_EDGE_RANK = {
    EdgeType.BLOCKS: 0, EdgeType.AFFECTS: 1, EdgeType.TOUCHES: 2, EdgeType.DEPENDS_ON: 3,
    EdgeType.OWNS: 4, EdgeType.DISCUSSES: 5, EdgeType.REFERENCES: 6, EdgeType.AUTHORED: 7,
}

_EDGE_TEMPLATES = {
    EdgeType.BLOCKS: "{src} blocks {dst}",
    EdgeType.AFFECTS: "{src} affects {dst}",
    EdgeType.TOUCHES: "{src} changes {dst}",
    EdgeType.DEPENDS_ON: "{src} depends on {dst}",
    EdgeType.REFERENCES: "{src} references {dst}",
    EdgeType.DISCUSSES: "{src} discusses {dst}",
    EdgeType.OWNS: "{src} owns {dst}",
    EdgeType.AUTHORED: "{src} authored {dst}",
}


class Reasoner(Protocol):
    def reason(self, evidence: EvidenceSet, risk_score: float) -> ReasoningProduced: ...


class TemplateReasoner:
    def __init__(self, *, max_clauses: int = 6) -> None:
        self._max_clauses = max_clauses

    def reason(self, evidence: EvidenceSet, risk_score: float) -> ReasoningProduced:
        anchor = evidence.anchor
        nodes = {n.id: n for n in evidence.nodes}
        by_label: dict[NodeLabel, list] = {}
        for n in evidence.nodes:
            by_label.setdefault(n.label, []).append(n)

        cited_nodes = {anchor.id}
        citations: list[Citation] = [
            Citation(ref_id=anchor.id, kind="node", label=anchor.label.value,
                     confidence=anchor.confidence)
        ]
        clauses: list[str] = []
        seen: set[str] = set()

        def cite_node(n) -> None:
            if n.id not in cited_nodes:
                cited_nodes.add(n.id)
                citations.append(Citation(ref_id=n.id, kind="node", label=n.label.value,
                                          confidence=n.confidence))

        # Highest-signal edges first, capped so the explanation stays readable. Every
        # clause cites its edge and both endpoints.
        for edge in sorted(evidence.edges, key=lambda e: _EDGE_RANK.get(e.type, 99)):
            src = nodes.get(edge.from_id)
            dst = nodes.get(edge.to_id)
            template = _EDGE_TEMPLATES.get(edge.type)
            if not src or not dst or not template:
                continue
            phrase = template.format(src=src.display(), dst=dst.display())
            if phrase in seen:
                continue
            seen.add(phrase)
            clauses.append(phrase)
            cite_node(src)
            cite_node(dst)
            citations.append(Citation(ref_id=edge.id, kind="edge", label=edge.type.value,
                                      confidence=edge.confidence))
            if len(clauses) >= self._max_clauses:
                break

        incidents = by_label.get(NodeLabel.INCIDENT, [])
        services = by_label.get(NodeLabel.SERVICE, [])
        owners = by_label.get(NodeLabel.PERSON, [])

        summary = f"{anchor.display()} is at risk (score {risk_score:.2f})."
        explanation = summary
        if clauses:
            explanation += " " + " ".join(f"{c}." for c in clauses)
        if incidents:
            sev = incidents[0].properties.get("severity", "an open incident")
            explanation += f" The blocking incident is {sev} and still open."

        actions: list[RecommendedAction] = []
        if incidents and services:
            actions.append(RecommendedAction(
                title="Hold the deployment until the incident clears",
                detail=f"{services[0].display()} is affected by {incidents[0].display()}; "
                       "deploying now risks a failed or rolled-back release.",
            ))
        if owners:
            actions.append(RecommendedAction(
                title=f"Loop in {owners[0].display()}",
                detail=f"{owners[0].display()} owns the affected service and is the "
                       "fastest path to resolution.",
            ))

        # Validate grounding: drop any citation not backed by the evidence set, and
        # derive confidence from the surviving citations.
        validator = GroundingValidator(evidence)
        grounded = validator.filter(citations)
        confidence = validator.confidence(grounded)

        return ReasoningProduced(
            node_id=anchor.id, summary=summary, explanation=explanation, actions=actions,
            citations=grounded, confidence=confidence, risk_score=risk_score,
        )
