"""Unit tests for the urgency scorer: monotonicity, bounds, and feature effects."""

from __future__ import annotations

from datetime import datetime, timezone

from cortex.contracts.enums import EdgeType, NodeLabel
from cortex.graph_sdk.models import Edge, Node
from cortex.services.ranking.scoring import UrgencyScorer


def _node(label: NodeLabel, key: str, **props: object) -> Node:
    return Node(id=f"nd_{key}", org_id="org", label=label, natural_key=key,
                source="test", properties=props, updated_at=datetime.now(timezone.utc))


def _edge(t: EdgeType, a: str, b: str, conf: float = 1.0) -> Edge:
    return Edge(id=f"eg_{a}_{b}", org_id="org", type=t, from_id=f"nd_{a}", to_id=f"nd_{b}",
                confidence=conf)


def test_score_is_bounded():
    scorer = UrgencyScorer()
    anchor = _node(NodeLabel.SERVICE, "svc")
    result = scorer.score(anchor, [anchor], [])
    assert 0.0 <= result.score <= 1.0


def test_open_sev1_scores_higher_than_bare_service():
    scorer = UrgencyScorer()
    bare = _node(NodeLabel.SERVICE, "svc", criticality="tier2")
    low = scorer.score(bare, [bare], [])

    incident = _node(NodeLabel.INCIDENT, "inc", severity="SEV1",
                     opened_at=datetime.now(timezone.utc).isoformat())
    svc = _node(NodeLabel.SERVICE, "svc", criticality="tier0")
    edges = [_edge(EdgeType.AFFECTS, "inc", "svc")]
    high = scorer.score(incident, [incident, svc], edges)

    assert high.score > low.score


def test_blocked_deployment_raises_score():
    scorer = UrgencyScorer()
    soon = datetime.now(timezone.utc).isoformat()
    deploy = _node(NodeLabel.DEPLOYMENT, "dep", scheduled_at=soon)
    ticket = _node(NodeLabel.TICKET, "tkt", priority="High")
    incident = _node(NodeLabel.INCIDENT, "inc", severity="SEV2",
                     opened_at=datetime.now(timezone.utc).isoformat())
    nodes = [deploy, ticket, incident]
    edges = [_edge(EdgeType.BLOCKS, "tkt", "dep"), _edge(EdgeType.BLOCKS, "inc", "tkt")]
    blocked = scorer.score(deploy, nodes, edges)

    lone = _node(NodeLabel.DEPLOYMENT, "dep2", scheduled_at=soon)
    unblocked = scorer.score(lone, [lone], [])
    # Being blocked by an open incident materially raises urgency over a bare deploy.
    assert blocked.score > unblocked.score
    assert blocked.score >= 0.5


def test_confidence_tracks_weakest_edge():
    scorer = UrgencyScorer()
    anchor = _node(NodeLabel.INCIDENT, "inc", severity="SEV2")
    svc = _node(NodeLabel.SERVICE, "svc")
    edges = [_edge(EdgeType.AFFECTS, "inc", "svc", conf=0.55)]
    result = scorer.score(anchor, [anchor, svc], edges)
    assert result.confidence == 0.55
