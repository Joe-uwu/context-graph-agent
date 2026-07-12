"""retrieval-service HTTP tests."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cortex.services.retrieval.http import create_app  # noqa: E402
from cortex.tools.wiring import Pipeline  # noqa: E402


@pytest.fixture
def client(pipeline: Pipeline) -> TestClient:
    return TestClient(create_app(pipeline.retrieval))


def test_ops_contract(client: TestClient, ops_contract) -> None:
    ops_contract(client)


def test_search_requires_org(client: TestClient) -> None:
    assert client.post("/api/v1/search", json={"query": "x"}).status_code == 401


def test_search_returns_hits(client: TestClient, org_id: str) -> None:
    r = client.post("/api/v1/search", json={"query": "billing"}, headers={"x-org-id": org_id})
    assert r.status_code == 200
    assert len(r.json()["data"]) >= 1


def test_evidence(client: TestClient, pipeline: Pipeline, org_id: str) -> None:
    top = pipeline.repo.top_by_urgency(org_id=org_id, limit=1)[0]
    r = client.get(f"/api/v1/evidence/{top.id}?hops=2", headers={"x-org-id": org_id})
    assert r.status_code == 200
    assert r.json()["data"]["anchor"]["id"] == top.id


def test_evidence_missing_404(client: TestClient, org_id: str) -> None:
    assert client.get("/api/v1/evidence/nope", headers={"x-org-id": org_id}).status_code == 404
