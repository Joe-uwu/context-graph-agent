"""End-to-end: the synthetic scenario must produce a grounded, bundled notification that
joins facts across at least three sources."""

from __future__ import annotations

from cortex.tools.wiring import Pipeline


def test_graph_joins_all_sources(pipeline: Pipeline, org_id: str):
    nodes = pipeline.repo.all_nodes(org_id=org_id)
    sources = {n.source for n in nodes}
    assert len(nodes) >= 10
    assert {"github", "jira", "pagerduty", "slack"} <= sources


def test_deployment_and_incident_are_high_risk(pipeline: Pipeline, org_id: str):
    top = pipeline.repo.top_by_urgency(org_id=org_id, limit=12, min_score=0.0)
    labels = {n.label.value for n in top[:6]}
    assert "Incident" in labels
    scores = [n.urgency for n in top]
    # Scores must spread, not all saturate at 1.0.
    assert max(scores) < 1.0
    assert max(scores) - min(scores) > 0.05


def test_exactly_one_bundled_interrupt(pipeline: Pipeline, org_id: str):
    slack_alerts = [n for n in pipeline.delivered if n.channel.value == "slack"]
    assert len(slack_alerts) == 1
    alert = slack_alerts[0]
    # The alert is grounded (confident) and names the cross-source chain.
    assert alert.confidence > 0.0
    body = alert.body.lower()
    assert "blocks" in body
    assert "affects billing" in body


def test_no_dead_letters(pipeline: Pipeline):
    assert pipeline.bus.dead_letters == []


def test_ack_suppresses_future_alerts(pipeline: Pipeline, org_id: str):
    # Acking the alert's node should stop it re-firing on re-score.
    alert = next(n for n in pipeline.delivered if n.channel.value == "slack")
    pipeline.notifications.suppress(alert.node_id)
    from cortex.contracts.payloads import ReasoningProduced
    again = pipeline.notifications.consider(
        ReasoningProduced(node_id=alert.node_id, summary="x", explanation="x",
                          confidence=1.0, risk_score=0.99)
    )
    assert again is None
