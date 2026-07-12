"""Event bus abstraction with an in-memory implementation.

Services depend only on the EventBus port; the runtime picks the implementation.
InMemoryEventBus runs the whole pipeline in one process (used for local dev, the demo,
and tests). KafkaEventBus (cortex.platform.kafka_bus, optional) is the production
implementation behind the same interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Deque

from cortex.contracts import Event, Topic
from cortex.platform.logging import bind_trace_id, get_logger

log = get_logger("cortex.bus")

EventHandler = Callable[[Event], None]


class EventBus(ABC):
    @abstractmethod
    def subscribe(self, topic: Topic, handler: EventHandler, *, group: str) -> None: ...

    @abstractmethod
    def publish(self, topic: Topic, event: Event) -> None: ...


class InMemoryEventBus(EventBus):
    """Synchronous in-process bus.

    Publishing enqueues; `drain()` processes the queue, so a handler that publishes
    downstream drives the pipeline without unbounded recursion. Delivery is
    at-least-once in spirit: a handler that raises after `max_retries` sends the event
    to an in-memory dead-letter list instead of blocking the pipeline.
    """

    def __init__(self, *, max_retries: int = 3) -> None:
        self._subs: dict[Topic, list[tuple[str, EventHandler]]] = defaultdict(list)
        self._queue: Deque[tuple[Topic, Event]] = deque()
        self._dlq: list[tuple[Topic, Event, str]] = []
        self._max_retries = max_retries
        self._published_count = 0

    def subscribe(self, topic: Topic, handler: EventHandler, *, group: str) -> None:
        self._subs[topic].append((group, handler))

    def publish(self, topic: Topic, event: Event) -> None:
        self._queue.append((topic, event))
        self._published_count += 1

    def drain(self) -> None:
        """Process every queued event and everything they transitively produce."""
        while self._queue:
            topic, event = self._queue.popleft()
            for group, handler in self._subs.get(topic, []):
                self._deliver(topic, event, group, handler)

    def _deliver(self, topic: Topic, event: Event, group: str, handler: EventHandler) -> None:
        bind_trace_id(event.trace_id)
        last_err = ""
        for attempt in range(1, self._max_retries + 1):
            try:
                handler(event)
                return
            except Exception as exc:  # noqa: BLE001 - bus is the last line of defense
                last_err = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "handler failed",
                    extra={"extra_fields": {
                        "topic": topic.value, "group": group,
                        "attempt": attempt, "error": last_err,
                    }},
                )
        self._dlq.append((topic, event, last_err))
        log.error(
            "sent to DLQ",
            extra={"extra_fields": {"topic": topic.dlq(), "event_id": event.event_id}},
        )

    # Introspection used by the demo and tests.
    @property
    def dead_letters(self) -> list[tuple[Topic, Event, str]]:
        return list(self._dlq)

    @property
    def published_count(self) -> int:
        return self._published_count
