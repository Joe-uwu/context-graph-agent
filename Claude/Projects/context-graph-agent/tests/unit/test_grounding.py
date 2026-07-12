"""Unit tests for the grounding validator: uncited claims are dropped, confidence tracks
the weakest cited edge."""

from __future__ import annotations

from cortex.contracts.enums import EdgeType, NodeLabel
from cortex.contracts.payloads import Citation
from cortex.graph_sdk.models import Edge, Node
from cortex.services.llm.grounding import GroundingValidator
from cortex.services.retrieval.service import EvidenceSet


def _evidence() -> EvidenceSet:
    anchor = Node(id="nd_dep", org_id="org", label=NodeLabel.DEPLOYMENT,
                  natural_key="dep", source="test")
    inc = Node(id="nd_inc", org_id="org", label=NodeLabel.INCIDENT,
               natural_key="inc", source="test", confidence=1.0)
    edge = Edge(id="eg_1", org_id="org", type=EdgeType.BLOCKS, from_id="nd_inc",
                to_id="nd_dep", confidence=0.6)
    return EvidenceSet(anchor=anchor, nodes=[anchor, inc], edges=[edge])


def test_resolved_citation_kept():
    v = GroundingValidator(_evidence())
    good = Citation(ref_id="eg_1", kind="edge", label="BLOCKS", confidence=0.6)
    assert v.resolves(good)
    assert v.filter([good]) == [good]


def test_unresolved_citation_dropped():
    v = GroundingValidator(_evidence())
    fabricated = Citation(ref_id="eg_does_not_exist", kind="edge", label="BLOCKS", confidence=1.0)
    assert not v.resolves(fabricated)
    assert v.filter([fabricated]) == []


def test_confidence_is_min_of_cited_edges():
    v = GroundingValidator(_evidence())
    node_cit = Citation(ref_id="nd_inc", kind="node", label="Incident", confidence=1.0)
    edge_cit = Citation(ref_id="eg_1", kind="edge", label="BLOCKS", confidence=0.6)
    assert v.confidence([node_cit, edge_cit]) == 0.6


def test_no_grounding_yields_zero_confidence():
    v = GroundingValidator(_evidence())
    fabricated = Citation(ref_id="nope", kind="edge", label="X", confidence=1.0)
    assert v.confidence([fabricated]) == 0.0
