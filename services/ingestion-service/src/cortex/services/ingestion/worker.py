"""Ingestion worker: pull from connectors, publish normalized raw.events."""

from __future__ import annotations

from collections.abc import Iterable

from cortex.contracts import Source, Topic, new_event
from cortex.contracts.payloads import RawEvent
from cortex.platform.bus import EventBus
from cortex.platform.logging import get_logger
from cortex.platform.observability import METRICS
from cortex.services.ingestion.ports import Connector

log = get_logger("cortex.ingestion")

PRODUCER = "ingestion-service@0.1.0"


class IngestionWorker:
    def __init__(self, bus: EventBus, org_id: str) -> None:
        self._bus = bus
        self._org_id = org_id
        self._connectors: list[Connector] = []
        self._published = 0

    def register(self, connector: Connector) -> None:
        self._connectors.append(connector)

    @property
    def connector_names(self) -> list[str]:
        return [getattr(c, "source", type(c).__name__) for c in self._connectors]

    @property
    def published(self) -> int:
        return self._published

    def run_initial_sync(self) -> int:
        """Backfill every connector once. Returns the number of events published."""
        count = 0
        for connector in self._connectors:
            for event in connector.initial_sync():
                self._publish(event)
                count += 1
        log.info("initial sync complete", extra={"extra_fields": {"events": count}})
        return count

    def run_incremental_sync(self, cursors: dict[str, str | None] | None = None) -> int:
        """Pull each connector since its cursor. Returns the number of events published."""
        cursors = cursors or {}
        count = 0
        for connector in self._connectors:
            for event in connector.incremental_sync(cursors.get(connector.source)):
                self._publish(event)
                count += 1
        return count

    def ingest(self, events: Iterable[RawEvent]) -> int:
        """Publish externally-sourced events (e.g. webhook deliveries) to raw.events."""
        count = 0
        for event in events:
            self._publish(event)
            count += 1
        return count

    def _publish(self, raw: RawEvent) -> None:
        assert isinstance(raw.source, Source)
        self._bus.publish(
            Topic.RAW_EVENTS,
            new_event(org_id=self._org_id, type="raw.event", payload=raw, producer=PRODUCER),
        )
        self._published += 1
        METRICS.inc("cortex_events_published_total", service="ingestion-service", source=raw.source.value)
