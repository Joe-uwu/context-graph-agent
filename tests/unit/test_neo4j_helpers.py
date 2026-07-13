"""Unit tests for the Neo4j adapter's pure serialization/parse helpers (no database)."""

from __future__ import annotations

from datetime import datetime, timezone

from cortex.contracts.enums import DiscoveredBy, EdgeType, NodeLabel
from cortex.graph_sdk.neo4j_repo import (
    _dumps,
    _edge_from_props,
    _loads,
    _node_from_props,
    _parse_dt,
)


def test_dumps_loads_roundtrip():
    value = {"name": "billing", "criticality": "tier0", "count": 3}
    assert _loads(_dumps(value)) == value


def test_loads_handles_empty_and_garbage():
    assert _loads(None) == {}
    assert _loads("") == {}
    assert _loads("not json") == {}
    assert _loads("[1,2,3]") == {}  # non-object JSON -> {}
    assert _loads({"already": "dict"}) == {"already": "dict"}


def test_parse_dt():
    assert _parse_dt(None) is None
    assert _parse_dt("garbage") is None
    dt = _parse_dt("2026-01-02T03:04:05Z")
    assert dt == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert _parse_dt("2026-01-02T03:04:05+00:00").tzinfo is not None


def test_node_from_props_rehydrates_json_fields():
    node = _node_from_props({
        "id": "nd_1", "org_id": "org", "label": "Service", "natural_key": "svc-billing",
        "source": "github", "properties_json": '{"name": "billing"}',
        "provenance": ["e1", "e2"], "urgency": 0.7,
        "urgency_features_json": '{"incident_severity": 1.0}', "confidence": 0.9,
    })
    assert node.label is NodeLabel.SERVICE
    assert node.properties == {"name": "billing"}
    assert node.provenance == ["e1", "e2"]
    assert node.urgency == 0.7
    assert node.urgency_features == {"incident_severity": 1.0}
    assert node.confidence == 0.9


def test_edge_from_props_rehydrates():
    edge = _edge_from_props(
        {
            "id": "eg_1", "confidence": 0.8, "discovered_by": "rule",
            "properties_json": '{"weight": 2}', "provenance": ["e1"],
            "valid_from": "2026-01-01T00:00:00Z", "valid_to": None,
        },
        org_id="org", type_=EdgeType.DEPENDS_ON, from_id="nd_1", to_id="nd_2",
    )
    assert edge.type is EdgeType.DEPENDS_ON
    assert edge.discovered_by is DiscoveredBy.RULE
    assert edge.properties == {"weight": 2}
    assert edge.from_id == "nd_1" and edge.to_id == "nd_2"
    assert edge.is_current  # valid_to is None
