"""Integration test for the API gateway over the live in-memory pipeline."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cortex.services.api.app import create_app  # noqa: E402
from cortex.tools.wiring import Pipeline  # noqa: E402


@pytest.fixture
def client(pipeline: Pipeline):
    app = create_app(pipeline.repo, pipeline.retrieval, pipeline.notifications)
    return TestClient(app)


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_top_risks_requires_org(client):
    assert client.get("/api/v1/risk/top").status_code == 401


def test_top_risks_scoped(client, org_id: str):
    r = client.get("/api/v1/risk/top", headers={"x-org-id": org_id})
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["org_id"] == org_id
    assert len(body["data"]) >= 1
    assert body["data"][0]["urgency"] > 0.0


def test_notifications_listed(client, org_id: str):
    r = client.get("/api/v1/notifications", headers={"x-org-id": org_id})
    data = r.json()["data"]
    assert any(n["channel"] == "slack" for n in data)


def test_search(client, org_id: str):
    r = client.post("/api/v1/search", json={"query": "billing"}, headers={"x-org-id": org_id})
    assert r.status_code == 200
    assert len(r.json()["data"]) >= 1
