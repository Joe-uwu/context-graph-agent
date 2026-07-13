"""Wire-format contract: the event envelope, payload schemas, topic catalog, and enum
values every service agrees on.

These are pure/offline and guard against silent, breaking drift — a renamed enum value or a
payload field change breaks the build, because producers and consumers in different services
rely on exactly these strings.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from cortex.contracts import (
    ChangeKind,
    EdgeType,
    Event,
    NodeLabel,
    NotificationChannel,
    Source,
    Topic,
    UserActionType,
    new_event,
)
from cortex.contracts.enums import DiscoveredBy
from cortex.contracts.payloads import (
    Citation,
    EntitiesExtracted,
    ExtractedEdge,
    ExtractedNode,
    GraphChanged,
    NotificationSent,
    RawEvent,
    ReasoningProduced,
    RecommendedAction,
    RiskScored,
    UserAction,
)
from pydantic import ValidationError


def _raw() -> RawEvent:
    return RawEvent(
        source=Source.GITHUB, kind="pull_request", external_id="pr-1",
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc), title="t", body="b",
    )


# --- envelope --------------------------------------------------------------------


def test_envelope_wraps_payload_and_generates_ids():
    ev = new_event(org_id="org_x", type="raw.event", payload=_raw(), producer="ingestion")
    assert ev.org_id == "org_x"
    assert ev.type == "raw.event"
    assert ev.producer == "ingestion"
    assert ev.event_id.startswith("evt_")
    assert len(ev.trace_id) == 32
    assert ev.schema_version == 1
    assert ev.payload["external_id"] == "pr-1"


def test_envelope_carries_trace_id_forward():
    ev = new_event(org_id="o", type="t", payload=_raw(), trace_id="abc123")
    assert ev.trace_id == "abc123"


def test_envelope_is_immutable():
    ev = new_event(org_id="o", type="t", payload=_raw())
    with pytest.raises(ValidationError):
        ev.org_id = "other"


def test_envelope_accepts_dict_payload():
    ev = new_event(org_id="o", type="t", payload={"k": "v"})
    assert ev.payload == {"k": "v"}


# --- payload round-trips ---------------------------------------------------------


def _roundtrip(model):
    cls = type(model)
    restored = cls.model_validate(model.model_dump(mode="json"))
    assert restored == model


def test_all_payloads_round_trip():
    _roundtrip(_raw())
    _roundtrip(EntitiesExtracted(
        source_event_id="evt_1",
        nodes=[ExtractedNode(label=NodeLabel.SERVICE, natural_key="svc", source=Source.GITHUB)],
        edges=[ExtractedEdge(type=EdgeType.AFFECTS, from_key="a", to_key="b",
                             discovered_by=DiscoveredBy.RULE)],
    ))
    _roundtrip(GraphChanged(changed_node_ids=["nd_1"], change_kind=ChangeKind.NODE_UPSERTED))
    _roundtrip(RiskScored(node_id="nd_1", score=0.9, confidence=0.8, features={"x": 1.0}))
    _roundtrip(ReasoningProduced(
        node_id="nd_1", summary="s", explanation="e",
        actions=[RecommendedAction(title="t", detail="d")],
        citations=[Citation(ref_id="nd_1", kind="node", label="Service", confidence=1.0)],
        confidence=0.8, risk_score=0.9,
    ))
    _roundtrip(NotificationSent(
        notification_id="ntf_1", node_id="nd_1", channel=NotificationChannel.SLACK,
        recipients=["oncall"], fingerprint="fp", title="t", body="b",
        risk_score=0.9, confidence=0.8,
    ))
    _roundtrip(UserAction(action=UserActionType.ACK, target_id="nd_1", actor="joe"))


def test_payload_validation_rejects_bad_enum():
    with pytest.raises(ValidationError):
        RawEvent(source="not_a_source", kind="k", external_id="x",
                 occurred_at=datetime.now(timezone.utc))


# --- topic catalog ---------------------------------------------------------------


def test_topic_values_and_dlq():
    assert Topic.RAW_EVENTS.value == "raw.events"
    assert Topic.ENTITIES_EXTRACTED.value == "entities.extracted"
    assert Topic.GRAPH_CHANGES.value == "graph.changes"
    assert Topic.RISK_SCORED.value == "risk.scored"
    assert Topic.REASONING_PRODUCED.value == "reasoning.produced"
    assert Topic.NOTIFICATIONS_SENT.value == "notifications.sent"
    assert Topic.USER_ACTIONS.value == "user.actions"
    assert Topic.RAW_EVENTS.dlq() == "raw.events.dlq"


# --- enum stability (breaking a value breaks the contract) -----------------------


def test_enum_values_are_stable():
    assert [s.value for s in Source] == [
        "github", "slack", "jira", "notion", "calendar", "pagerduty", "derived",
    ]
    assert ChangeKind.NODE_UPSERTED.value == "node_upserted"
    assert DiscoveredBy.RULE.value == "rule"
    assert {c.value for c in NotificationChannel} == {
        "dashboard", "slack", "email", "webhook", "digest",
    }
    assert {a.value for a in UserActionType} == {"ack", "dismiss", "snooze"}
    # A few load-bearing labels/edges used across scoring, extraction, and the API.
    assert NodeLabel.INCIDENT.value == "Incident"
    assert NodeLabel.SERVICE.value == "Service"
    assert EdgeType.BLOCKS.value == "BLOCKS"
    assert EdgeType.AFFECTS.value == "AFFECTS"


def test_event_json_serializable():
    ev = new_event(org_id="o", type="t", payload=_raw())
    assert isinstance(Event.model_validate_json(ev.model_dump_json()), Event)
