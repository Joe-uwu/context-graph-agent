"""notification-service HTTP tests."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cortex.services.notification.http import create_app  # noqa: E402
from cortex.tools.wiring import Pipeline  # noqa: E402


@pytest.fixture
def client(pipeline: Pipeline) -> TestClient:
    return TestClient(create_app(pipeline.notifications))


def test_ops_contract(client: TestClient, ops_contract) -> None:
    ops_contract(client)


def test_feed_has_interrupt(client: TestClient, org_id: str) -> None:
    data = client.get("/api/v1/notifications", headers={"x-org-id": org_id}).json()["data"]
    assert len(data) >= 1
    assert any(n["channel"] == "slack" for n in data)


def test_ack_action_recorded(client: TestClient, org_id: str) -> None:
    feed = client.get("/api/v1/notifications", headers={"x-org-id": org_id}).json()["data"]
    target = feed[0]["node_id"]
    r = client.post(
        "/api/v1/actions",
        json={"action": "ack", "target_id": target, "actor": "joe"},
        headers={"x-org-id": org_id},
    )
    assert r.status_code == 200
    assert r.json()["data"]["action"] == "ack"


def test_bad_action_422(client: TestClient, org_id: str) -> None:
    r = client.post(
        "/api/v1/actions",
        json={"action": "explode", "target_id": "x", "actor": "joe"},
        headers={"x-org-id": org_id},
    )
    assert r.status_code == 422
