"""Entity worker: consume raw.events, extract typed entities, produce entities.extracted."""

from __future__ import annotations

from cortex.contracts import Event, Topic, new_event
from cortex.contracts.payloads import RawEvent
from cortex.platform.bus import EventBus
from cortex.platform.logging import get_logger
from cortex.platform.observability import METRICS
from cortex.services.entity.extractors import extract

log = get_logger("cortex.entity")

PRODUCER = "entity-service@0.1.0"


class EntityWorker:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._processed = 0
        self._nodes_out = 0
        bus.subscribe(Topic.RAW_EVENTS, self.handle, group="entity-service")

    @property
    def processed(self) -> int:
        return self._processed

    @property
    def nodes_extracted(self) -> int:
        return self._nodes_out

    def handle(self, event: Event) -> None:
        raw = RawEvent.model_validate(event.payload)
        extracted = extract(raw)
        self._processed += 1
        METRICS.inc("cortex_events_processed_total", service="entity-service")
        if not extracted.nodes:
            return
        self._nodes_out += len(extracted.nodes)
        self._bus.publish(
            Topic.ENTITIES_EXTRACTED,
            new_event(
                org_id=event.org_id, type="entities.extracted", payload=extracted,
                producer=PRODUCER, trace_id=event.trace_id,
            ),
        )
        log.info("extracted", extra={"extra_fields": {
            "nodes": len(extracted.nodes), "edges": len(extracted.edges),
        }})
