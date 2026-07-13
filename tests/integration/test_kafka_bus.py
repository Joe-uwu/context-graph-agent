"""KafkaEventBus integration test — a real publish → consume → dispatch round-trip.

Skips unless a broker is configured (`CORTEX_KAFKA_BOOTSTRAP`), confluent-kafka is installed,
and the broker is reachable. CI runs it against an apache/kafka service container (kafka-it).
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone

import pytest
from cortex.contracts import Topic, new_event
from cortex.contracts.enums import Source
from cortex.contracts.payloads import RawEvent


def _bus_or_skip():
    bootstrap = os.environ.get("CORTEX_KAFKA_BOOTSTRAP")
    if not bootstrap:
        pytest.skip("CORTEX_KAFKA_BOOTSTRAP not set")
    pytest.importorskip("confluent_kafka")
    from confluent_kafka.admin import AdminClient

    try:
        # Force a metadata fetch so an unreachable broker skips rather than hangs the suite.
        AdminClient({"bootstrap.servers": bootstrap}).list_topics(timeout=5)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"kafka unreachable: {exc}")

    from cortex.platform.kafka_bus import KafkaEventBus

    return KafkaEventBus(bootstrap, client_id=f"test-{uuid.uuid4().hex[:6]}")


def test_publish_consume_roundtrip():
    bus = _bus_or_skip()
    received: list = []
    group = f"test-group-{uuid.uuid4().hex[:8]}"  # fresh group -> reads from earliest
    bus.subscribe(Topic.USER_ACTIONS, received.append, group=group)

    consumer = threading.Thread(target=bus.run, args=(group,), daemon=True)
    consumer.start()
    time.sleep(3)  # let the consumer join the group

    raw = RawEvent(
        source=Source.GITHUB, kind="k", external_id="kafka-it-1",
        occurred_at=datetime.now(timezone.utc),
    )
    event = new_event(org_id="org_test", type="raw.event", payload=raw, trace_id="t-kafka-1")
    bus.publish(Topic.USER_ACTIONS, event)

    deadline = time.time() + 25
    while time.time() < deadline and not received:
        time.sleep(0.5)

    assert received, "event was published but never consumed"
    got = next((e for e in received if e.payload.get("external_id") == "kafka-it-1"), None)
    assert got is not None
    assert got.org_id == "org_test"
    assert got.trace_id == "t-kafka-1"
