"""Shared fixtures for per-service HTTP contract tests.

`ops_contract` returns a checker that asserts the ops surface every service shares:
liveness, readiness, Prometheus metrics, and a valid OpenAPI document. Individual service
tests add their own domain-route assertions on top.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

pytest.importorskip("fastapi")


def _check(client) -> None:
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").status_code in (200, 503)
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "# TYPE" in metrics.text
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    assert spec.json()["info"]["title"].startswith("Cortex")


@pytest.fixture
def ops_contract() -> Callable[[object], None]:
    return _check
