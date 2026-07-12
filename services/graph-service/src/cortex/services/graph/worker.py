"""Graph worker: consume entities.extracted, write the graph, emit graph.changes."""

from __future__ import annotations

from cortex.contracts import ChangeKind, Event, Topic, new_event
from cortex.contracts.payloads import EntitiesExtracted, GraphChanged
from cortex.graph_sdk.repository import GraphRepository
from cortex.platform.bus import EventBus
from cortex.platform.logging import get_logger
from cortex.platform.observability import METRICS
from cortex.services.graph.discovery import RelationshipDiscovery

log = get_logger("cortex.graph")

PRODUCER = "graph-service@0.1.0"


class GraphWorker:
    def __init__(
        self, bus: EventBus, repo: GraphRepository,
        discovery: RelationshipDiscovery | None = None,
    ) -> None:
        self._bus = bus
        self._repo = repo
        self._discovery = discovery or RelationshipDiscovery()
        bus.subscribe(Topic.ENTITIES_EXTRACTED, self.handle, group="graph-service")

    def handle(self, event: Event) -> None:
        extracted = EntitiesExtracted.model_validate(event.payload)
        org = event.org_id
        evt_id = event.event_id

        # Resolve + write nodes; map natural_key -> node id.
        key_to_id: dict[str, str] = {}
        changed: list[str] = []
        for n in extracted.nodes:
            node = self._repo.upsert_node(
                org_id=org, label=n.label, natural_key=n.natural_key, source=n.source.value,
                properties=n.properties, provenance_event_id=evt_id, confidence=n.confidence,
            )
            key_to_id[n.natural_key] = node.id
            changed.append(node.id)

        # Discover + write edges (rule tier already present; embedding/llm tiers optional).
        edges = self._discovery.discover(extracted.nodes, extracted.edges)
        for e in edges:
            frm = key_to_id.get(e.from_key)
            to = key_to_id.get(e.to_key)
            if not frm or not to:
                continue  # edge references a node not in this batch; skip until it arrives
            self._repo.upsert_edge(
                org_id=org, type=e.type, from_id=frm, to_id=to, confidence=e.confidence,
                discovered_by=e.discovered_by.value, provenance_event_id=evt_id,
                properties=e.properties,
            )

        METRICS.inc("cortex_events_processed_total", service="graph-service")
        METRICS.inc("cortex_graph_nodes_upserted_total", float(len(changed)), service="graph-service")
        if not changed:
            return
        self._bus.publish(
            Topic.GRAPH_CHANGES,
            new_event(
                org_id=org, type="graph.changed", producer=PRODUCER, trace_id=event.trace_id,
                payload=GraphChanged(changed_node_ids=changed, change_kind=ChangeKind.NODE_UPSERTED),
            ),
        )
        log.info("graph updated", extra={"extra_fields": {"changed": len(changed)}})
