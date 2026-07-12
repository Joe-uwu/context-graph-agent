"""graph-service HTTP tests (served over the seeded in-memory pipeline)."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cortex.services.graph.http import create_app  # noqa: E402
from cortex.tools.wiring import Pipeline  # noqa: E402


@pytest.fixture
def client(pipeline: Pipeline) -> TestClient:
    return TestClient(create_app(pipeline.repo))


def test_ops_contract(client: TestClient, ops_contract) -> None:
    ops_contract(client)


def test_stats_requires_org(client: TestClient) -> None:
    assert client.get("/api/v1/stats").status_code == 401


def test_stats_scoped(client: TestClient, org_id: str) -> None:
    body = client.get("/api/v1/stats", headers={"x-org-id": org_id}).json()
    assert body["data"]["nodes"] > 0
    assert body["data"]["by_label"]


def test_node_and_neighborhood(client: TestClient, pipeline: Pipeline, org_id: str) -> None:
    top = pipeline.repo.top_by_urgency(org_id=org_id, limit=1)[0]
    h = {"x-org-id": org_id}
    node = client.get(f"/api/v1/nodes/{top.id}", headers=h)
    assert node.status_code == 200
    assert node.json()["data"]["node"]["id"] == top.id
    nb = client.get(f"/api/v1/nodes/{top.id}/neighborhood?hops=2", headers=h)
    assert nb.status_code == 200
    assert len(nb.json()["data"]["nodes"]) >= 1


def test_missing_node_404(client: TestClient, org_id: str) -> None:
    assert client.get("/api/v1/nodes/nope", headers={"x-org-id": org_id}).status_code == 404
