"""ingestion-service HTTP + worker tests."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cortex.contracts import Topic  # noqa: E402
from cortex.platform.bus import InMemoryEventBus  # noqa: E402
from cortex.services.ingestion.connectors.mock import MockConnector  # noqa: E402
from cortex.services.ingestion.http import create_app  # noqa: E402
from cortex.services.ingestion.worker import IngestionWorker  # noqa: E402
from cortex.tools.synthetic.scenario import ORG_ID, deploy_will_fail_scenario  # noqa: E402


@pytest.fixture
def worker() -> IngestionWorker:
    w = IngestionWorker(InMemoryEventBus(), ORG_ID)
    w.register(MockConnector("mixed", deploy_will_fail_scenario()))
    return w


@pytest.fixture
def client(worker: IngestionWorker) -> TestClient:
    return TestClient(create_app(worker))


def test_ops_contract(client: TestClient, ops_contract) -> None:
    ops_contract(client)


def test_connectors_listed(client: TestClient) -> None:
    assert client.get("/api/v1/connectors").json()["data"] == ["mixed"]


def test_sync_publishes(client: TestClient) -> None:
    published = client.post("/api/v1/sync").json()["data"]["published"]
    assert published > 0
    assert client.get("/api/v1/stats").json()["data"]["events_published"] == published


def test_worker_publishes_raw_events() -> None:
    bus = InMemoryEventBus()
    seen: list = []
    bus.subscribe(Topic.RAW_EVENTS, seen.append, group="test")
    w = IngestionWorker(bus, ORG_ID)
    w.register(MockConnector("mixed", deploy_will_fail_scenario()))
    count = w.run_initial_sync()
    bus.drain()
    assert count == len(seen) > 0


def test_github_webhook_route_verifies_and_publishes() -> None:
    import json

    from cortex.services.ingestion.connectors.github.webhooks import sign
    from cortex.services.ingestion.http import create_app

    bus = InMemoryEventBus()
    published: list = []
    bus.subscribe(Topic.RAW_EVENTS, published.append, group="test")
    worker = IngestionWorker(bus, ORG_ID)
    app = create_app(worker, webhook_secret="s3cret")
    client = TestClient(app)

    body = json.dumps({
        "action": "opened",
        "repository": {"full_name": "acme/web"},
        "pull_request": {"number": 9, "title": "T", "user": {"login": "joe"},
                         "updated_at": "2026-01-01T00:00:00Z", "labels": []},
    }).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": sign("s3cret", body),
        "X-GitHub-Delivery": "d-1",
        "Content-Type": "application/json",
    }
    r = client.post("/webhooks/github", content=body, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["published"] == 1
    bus.drain()
    assert len(published) == 1

    # Wrong signature is rejected and nothing is published.
    bad = client.post("/webhooks/github", content=body,
                      headers={**headers, "X-Hub-Signature-256": "sha256=bad"})
    assert bad.status_code == 401
