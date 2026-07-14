"""LangGraph port tests: the real langgraph runtime executes the nine nodes and matches the
native engine's output (grounded citations, LLM plug-in, isolated-node halt)."""

from __future__ import annotations

import pytest

from cortex.contracts.enums import EdgeType, NodeLabel
from cortex.graph_sdk.memory import InMemoryGraphRepository
from cortex.services.llm.graph import GraphReasoner, ReasoningConfig, langgraph_available
from cortex.services.retrieval.service import RetrievalService

pytestmark = pytest.mark.skipif(not langgraph_available(), reason="langgraph not installed")

ORG = "org_test"


def _evidence(*, isolated: bool = False):
    repo = InMemoryGraphRepository()
    svc = repo.upsert_node(org_id=ORG, label=NodeLabel.SERVICE, natural_key="svc-billing",
                           source="github", properties={"name": "billing-service"},
                           provenance_event_id="e1")
    if isolated:
        return RetrievalService(repo).gather_evidence(org_id=ORG, node_id=svc.id, hops=2), svc
    inc = repo.upsert_node(org_id=ORG, label=NodeLabel.INCIDENT, natural_key="inc-1",
                           source="pagerduty", properties={"severity": "SEV1"},
                           provenance_event_id="e2")
    owner = repo.upsert_node(org_id=ORG, label=NodeLabel.PERSON, natural_key="dana",
                             source="github", properties={"name": "Dana"}, provenance_event_id="e3")
    repo.upsert_edge(org_id=ORG, type=EdgeType.AFFECTS, from_id=inc.id, to_id=svc.id,
                     confidence=0.9, discovered_by="rule", provenance_event_id="e4")
    repo.upsert_edge(org_id=ORG, type=EdgeType.OWNS, from_id=owner.id, to_id=svc.id,
                     confidence=1.0, discovered_by="rule", provenance_event_id="e5")
    return RetrievalService(repo).gather_evidence(org_id=ORG, node_id=svc.id, hops=2), svc


def _reasoner(**cfg):
    from cortex.services.llm.graph import LangGraphReasoner
    return LangGraphReasoner(ReasoningConfig(**cfg))


def test_langgraph_runs_full_pipeline_grounded():
    ev, svc = _evidence()
    result = _reasoner().reason(ev, 0.9)
    assert result.node_id == svc.id
    assert result.summary and result.explanation
    assert len(result.citations) >= 2
    assert 0.0 < result.confidence <= 1.0
    assert any("Hold the deployment" in a.title for a in result.actions)


def test_langgraph_matches_native_engine():
    ev, _ = _evidence()
    native = GraphReasoner(ReasoningConfig()).reason(ev, 0.9)
    lg = _reasoner().reason(ev, 0.9)
    assert lg.summary == native.summary
    assert {c.ref_id for c in lg.citations} == {c.ref_id for c in native.citations}
    assert [a.title for a in lg.actions] == [a.title for a in native.actions]


def test_langgraph_uses_llm_plugin():
    class _FakeLlm:
        def reason(self, *, anchor_display, risk_score, findings, entities):
            return {"summary": "LLM summary", "explanation": "LLM explanation",
                    "actions": [{"title": "Do the LLM thing", "detail": "model"}]}

    ev, _ = _evidence()
    result = _reasoner(llm=_FakeLlm()).reason(ev, 0.9)
    assert result.summary == "LLM summary"
    assert any(a.title == "Do the LLM thing" for a in result.actions)
    assert result.citations  # grounding still runs on the langgraph runtime


def test_langgraph_halts_on_isolated_node():
    iso, svc = _evidence(isolated=True)
    result = _reasoner().reason(iso, 0.9)
    assert result.node_id == svc.id
    assert result.actions == []


def test_build_reasoner_selects_langgraph():
    from types import SimpleNamespace

    from cortex.services.llm.graph import LangGraphReasoner, build_reasoner

    r = build_reasoner(SimpleNamespace(evidence_hops=3, reasoner_engine="langgraph"))
    assert isinstance(r, LangGraphReasoner)
