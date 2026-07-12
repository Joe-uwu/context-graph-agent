"""Production event bus backed by Kafka (confluent-kafka).

Same EventBus interface as InMemoryEventBus so services are unaware which one runs.
Requires the `kafka` extra. Messages are keyed by org_id (per-tenant ordering),
serialized as the Event envelope JSON. Offsets commit after the handler returns
(at-least-once); failures route to the topic's DLQ.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable

from cortex.contracts import Event, Topic
from cortex.platform.bus import EventBus
from cortex.platform.logging import bind_trace_id, get_logger

log = get_logger("cortex.kafka_bus")

EventHandler = Callable[[Event], None]


class KafkaEventBus(EventBus):
    def __init__(self, bootstrap: str, *, client_id: str, max_retries: int = 3) -> None:
        try:
            from confluent_kafka import Consumer, Producer
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("KafkaEventBus requires the 'kafka' extra") from exc
        self._producer = Producer({"bootstrap.servers": bootstrap, "client.id": client_id})
        self._bootstrap = bootstrap
        self._client_id = client_id
        self._max_retries = max_retries
        self._handlers: dict[Topic, list[tuple[str, EventHandler]]] = defaultdict(list)
        self._Consumer = Consumer

    def subscribe(self, topic: Topic, handler: EventHandler, *, group: str) -> None:
        self._handlers[topic].append((group, handler))

    def publish(self, topic: Topic, event: Event) -> None:
        self._producer.produce(
            topic.value,
            key=event.org_id.encode(),
            value=event.model_dump_json().encode(),
        )
        self._producer.poll(0)

    def run(self, group: str) -> None:  # pragma: no cover - requires a live broker
        """Blocking consume loop for one consumer group across its subscribed topics."""
        topics = [t.value for t, subs in self._handlers.items() if any(g == group for g, _ in subs)]
        consumer = self._Consumer({
            "bootstrap.servers": self._bootstrap,
            "group.id": group,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        })
        consumer.subscribe(topics)
        try:
            while True:
                msg = consumer.poll(1.0)
                if msg is None:
                    continue
                if msg.error():
                    log.error("consume error", extra={"extra_fields": {"error": str(msg.error())}})
                    continue
                event = Event.model_validate_json(msg.value())
                topic = Topic(msg.topic())
                self._dispatch(topic, event, group)
                consumer.commit(msg, asynchronous=False)
        finally:
            consumer.close()

    def _dispatch(self, topic: Topic, event: Event, group: str) -> None:
        bind_trace_id(event.trace_id)
        for g, handler in self._handlers.get(topic, []):
            if g != group:
                continue
            for attempt in range(1, self._max_retries + 1):
                try:
                    handler(event)
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == self._max_retries:
                        self._producer.produce(topic.dlq(), value=json.dumps({
                            "event": event.model_dump(mode="json"), "error": str(exc),
                        }).encode())
                        self._producer.poll(0)
