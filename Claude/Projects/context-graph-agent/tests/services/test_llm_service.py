"""llm-service HTTP tests."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cortex.services.llm.http import create_app  # noqa: E402
from cortex.services.llm.reasoning import TemplateReasoner  # noqa: E402
from cortex.tools.wiring import Pipeline  # noqa: E402


@pytest.fixture
def client(pipeline: Pipeline) -> TestClient:
    return TestClient(create_app(pipeline.retrieval, TemplateReasoner()))


def test_ops_contract(client: TestClient, ops_contract) -> None:
    ops_contract(client)


def test_reason_produces_grounded_output(
    client: TestClient, pipeline: Pipeline, org_id: str
) -> None:
    top = pipeline.repo.top_by_urgency(org_id=org_id, limit=1)[0]
    r = client.post("/api/v1/reason", json={"node_id": top.id}, headers={"x-org-id": org_id})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["summary"]
    # Every claim must be grounded: the reasoner emits citations pointing at graph evidence.
    assert len(data["citations"]) >= 1


def test_reason_missing_404(client: TestClient, org_id: str) -> None:
    r = client.post("/api/v1/reason", json={"node_id": "nope"}, headers={"x-org-id": org_id})
    assert r.status_code == 404
