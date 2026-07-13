"""Reasoning-graph tests: engine mechanics, each node in isolation, and the full pipeline."""

from __future__ import annotations

from cortex.contracts.enums import EdgeType, NodeLabel
from cortex.graph_sdk.memory import InMemoryGraphRepository
from cortex.services.llm.graph import GraphReasoner, ReasoningConfig
from cortex.services.llm.graph import nodes as N
from cortex.services.llm.graph.engine import END, StateGraph
from cortex.services.llm.graph.pipeline import build_reasoning_graph
from cortex.services.llm.graph.state import ReasoningState
from cortex.services.retrieval.service import RetrievalService

ORG = "org_test"


def _state(**kw) -> ReasoningState:
    base = {"org_id": ORG, "node_id": "nd", "risk_score": 0.5}
    base.update(kw)
    return ReasoningState(**base)


def _evidence(*, isolated: bool = False):
    repo = InMemoryGraphRepository()
    svc = repo.upsert_node(org_id=ORG, label=NodeLabel.SERVICE, natural_key="svc-billing",
                           source="github", properties={"name": "billing-service"},
                           provenance_event_id="e1")
    if isolated:
        retrieval = RetrievalService(repo)
        return retrieval.gather_evidence(org_id=ORG, node_id=svc.id, hops=2), svc
    inc = repo.upsert_node(org_id=ORG, label=NodeLabel.INCIDENT, natural_key="inc-1",
                           source="pagerduty", properties={"severity": "SEV1"},
                           provenance_event_id="e2")
    owner = repo.upsert_node(org_id=ORG, label=NodeLabel.PERSON, natural_key="dana",
                             source="github", properties={"name": "Dana"}, provenance_event_id="e3")
    repo.upsert_edge(org_id=ORG, type=EdgeType.AFFECTS, from_id=inc.id, to_id=svc.id,
                     confidence=0.9, discovered_by="rule", provenance_event_id="e4")
    repo.upsert_edge(org_id=ORG, type=EdgeType.OWNS, from_id=owner.id, to_id=svc.id,
                     confidence=1.0, discovered_by="rule", provenance_event_id="e5")
    retrieval = RetrievalService(repo)
    return retrieval.gather_evidence(org_id=ORG, node_id=svc.id, hops=2), svc


# --- engine mechanics ------------------------------------------------------------


def test_engine_retries_then_succeeds():
    calls = {"n": 0}

    def flaky(state, deps):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")
        state.summary = "ok"
        return state

    graph = StateGraph().add_node("a", flaky, retries=3).set_entry("a")
    graph.add_edge("a", END)
    result = graph.run(_state())
    assert result.summary == "ok"
    assert calls["n"] == 2 and not result.halted


def test_engine_halts_after_exhausting_retries():
    def always(state, deps):
        raise RuntimeError("boom")

    graph = StateGraph().add_node("a", always, retries=2).set_entry("a")
    graph.add_edge("a", END)
    result = graph.run(_state())
    assert result.halted and "failed" in result.halt_reason
    assert "a:error" in result.trace


def test_conditional_edge_routes_both_ways():
    graph = StateGraph()
    graph.add_node("check", lambda s, d: s).set_entry("check")
    graph.add_node("yes", lambda s, d: (setattr(s, "summary", "yes"), s)[1])
    graph.add_node("no", lambda s, d: (setattr(s, "summary", "no"), s)[1])
    graph.add_conditional("check", lambda s: s.verified, "yes", "no")
    graph.add_edge("yes", END)
    graph.add_edge("no", END)
    assert graph.run(_state(verified=True)).summary == "yes"
    assert graph.run(_state(verified=False)).summary == "no"


# --- nodes in isolation ----------------------------------------------------------


def test_observe_clamps_risk():
    assert N.observe(_state(risk_score=1.5), None).risk_score == 1.0
    assert N.observe(_state(risk_score=-0.2), None).risk_score == 0.0


def test_verify_gates_on_evidence():
    ev, svc = _evidence()
    verified = N.verify(_state(node_id=svc.id, evidence=ev), None)
    assert verified.verified

    iso, svc2 = _evidence(isolated=True)
    rejected = N.verify(_state(node_id=svc2.id, evidence=iso), None)
    assert not rejected.verified and "isolated" in rejected.verify_reason


def test_graph_traverse_builds_findings():
    ev, svc = _evidence()
    state = N.graph_traverse(_state(node_id=svc.id, evidence=ev), ReasoningConfig())
    assert state.findings  # edges -> clauses
    assert state.incidents and state.services and state.owners
    assert all(f.node_ids for f in state.findings)


def test_ground_only_keeps_resolvable_citations():
    ev, svc = _evidence()
    cfg = ReasoningConfig()
    state = N.graph_traverse(_state(node_id=svc.id, evidence=ev), cfg)
    state = N.ground(state, cfg)
    assert state.citations
    node_ids = {n.id for n in ev.nodes}
    edge_ids = {e.id for e in ev.edges}
    for c in state.citations:
        assert (c.ref_id in node_ids) if c.kind == "node" else (c.ref_id in edge_ids)
    assert 0.0 < state.confidence <= 1.0


def test_recommend_and_notify():
    ev, svc = _evidence()
    cfg = ReasoningConfig(interrupt_at=0.75)
    state = N.graph_traverse(_state(node_id=svc.id, risk_score=0.9, evidence=ev), cfg)
    state = N.ground(state, cfg)
    state = N.recommend(state, cfg)
    assert any("Hold the deployment" in a.title for a in state.actions)
    state = N.notify(state, cfg)
    assert state.should_notify and state.channel_hint == "slack"


# --- full pipeline ---------------------------------------------------------------


def test_pipeline_produces_grounded_reasoning():
    ev, svc = _evidence()
    result = GraphReasoner(ReasoningConfig()).reason(ev, 0.9)
    assert result.node_id == svc.id
    assert result.summary and result.explanation
    assert len(result.citations) >= 2
    assert 0.0 < result.confidence <= 1.0
    assert any("Hold the deployment" in a.title for a in result.actions)


def test_pipeline_runs_all_nine_nodes_in_order():
    ev, _ = _evidence()
    graph = build_reasoning_graph()
    state = ReasoningState(org_id=ORG, node_id=ev.anchor.id, risk_score=0.9, evidence=ev)
    final = graph.run(state, ReasoningConfig())
    assert final.trace == [
        "observe", "retrieve", "verify", "graph_traverse", "reason",
        "ground", "explain", "recommend", "notify",
    ]


def test_pipeline_halts_on_isolated_node():
    iso, svc = _evidence(isolated=True)
    result = GraphReasoner(ReasoningConfig()).reason(iso, 0.9)
    # Verify rejects the isolated node; still returns a valid (minimal) payload.
    assert result.node_id == svc.id
    assert result.actions == []


def test_run_from_trigger_uses_retrieval():
    ev, svc = _evidence()

    class _FakeRetrieval:
        def gather_evidence(self, *, org_id, node_id, hops):
            return ev

    reasoner = GraphReasoner(ReasoningConfig(retrieval=_FakeRetrieval()))
    state = reasoner.run_from_trigger(org_id=ORG, node_id=svc.id, risk_score=0.9)
    assert "retrieve" in state.trace and state.evidence is ev
    assert state.trace[-1] == "notify"
