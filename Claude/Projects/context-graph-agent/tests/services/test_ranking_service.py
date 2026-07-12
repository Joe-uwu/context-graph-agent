"""ranking-service HTTP tests."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cortex.services.ranking.http import create_app  # noqa: E402
from cortex.services.ranking.scoring import UrgencyScorer  # noqa: E402
from cortex.tools.wiring import Pipeline  # noqa: E402


@pytest.fixture
def client(pipeline: Pipeline) -> TestClient:
    return TestClient(create_app(pipeline.repo, UrgencyScorer()))


def test_ops_contract(client: TestClient, ops_contract) -> None:
    ops_contract(client)


def test_weights_exposed(client: TestClient) -> None:
    weights = client.get("/api/v1/weights").json()["data"]
    assert "incident_severity" in weights


def test_score_on_demand(client: TestClient, pipeline: Pipeline, org_id: str) -> None:
    top = pipeline.repo.top_by_urgency(org_id=org_id, limit=1)[0]
    r = client.post("/api/v1/score", json={"node_id": top.id}, headers={"x-org-id": org_id})
    assert r.status_code == 200
    data = r.json()["data"]
    assert 0.0 <= data["score"] <= 1.0
    assert data["features"]


def test_score_missing_404(client: TestClient, org_id: str) -> None:
    r = client.post("/api/v1/score", json={"node_id": "nope"}, headers={"x-org-id": org_id})
    assert r.status_code == 404
