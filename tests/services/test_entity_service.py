"""entity-service HTTP + worker tests."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cortex.contracts import Topic  # noqa: E402
from cortex.platform.bus import InMemoryEventBus  # noqa: E402
from cortex.services.entity.http import create_app  # noqa: E402
from cortex.services.entity.worker import EntityWorker  # noqa: E402
from cortex.tools.synthetic.scenario import deploy_will_fail_scenario  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(EntityWorker(InMemoryEventBus())))


def test_ops_contract(client: TestClient, ops_contract) -> None:
    ops_contract(client)


def test_extract_returns_entities(client: TestClient) -> None:
    # At least one synthetic source event must yield extracted nodes.
    total = 0
    for raw in deploy_will_fail_scenario():
        r = client.post("/api/v1/extract", json=raw.model_dump(mode="json"))
        assert r.status_code == 200, r.text
        total += r.json()["meta"]["nodes"]
    assert total > 0


def test_worker_publishes_extracted() -> None:
    bus = InMemoryEventBus()
    worker = EntityWorker(bus)
    published: list = []
    bus.subscribe(Topic.ENTITIES_EXTRACTED, published.append, group="test")
    for raw in deploy_will_fail_scenario():
        from cortex.contracts import new_event

        worker.handle(new_event(org_id="org_demo", type="raw.event", payload=raw))
    bus.drain()
    assert worker.processed == len(deploy_will_fail_scenario())
    assert len(published) > 0
