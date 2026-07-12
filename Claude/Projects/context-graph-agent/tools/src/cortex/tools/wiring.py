"""Wire the whole pipeline onto one in-memory bus.

This is the composition root for local/demo/test runs: it constructs the bus, the graph
repository, and every service worker, and returns handles the caller needs. In
production each worker is its own process consuming from Kafka; the wiring is the same
shape, only the bus and repository implementations differ.
"""

from __future__ import annotations

from dataclasses import dataclass

from cortex.graph_sdk import GraphRepository, InMemoryGraphRepository
from cortex.platform.bus import InMemoryEventBus
from cortex.services.entity.worker import EntityWorker
from cortex.services.graph.worker import GraphWorker
from cortex.services.ingestion.connectors.mock import MockConnector
from cortex.services.ingestion.worker import IngestionWorker
from cortex.services.llm.worker import LlmWorker
from cortex.services.notification.engine import Notification, NotificationEngine
from cortex.services.notification.worker import NotificationWorker
from cortex.services.ranking.worker import RankingWorker
from cortex.services.retrieval.service import RetrievalService


@dataclass
class Pipeline:
    bus: InMemoryEventBus
    repo: GraphRepository
    ingestion: IngestionWorker
    retrieval: RetrievalService
    notifications: NotificationEngine
    delivered: list[Notification]

    def run_scenario(self, raw_events: list) -> None:
        """Feed source events through the mock connector and drain the pipeline."""
        connector = MockConnector("mixed", raw_events)
        self.ingestion.register(connector)
        self.ingestion.run_initial_sync()
        self.bus.drain()


def build_pipeline(org_id: str, *, evidence_hops: int = 4) -> Pipeline:
    bus = InMemoryEventBus()
    repo: GraphRepository = InMemoryGraphRepository()
    retrieval = RetrievalService(repo)
    delivered: list[Notification] = []

    ingestion = IngestionWorker(bus, org_id)
    EntityWorker(bus)
    GraphWorker(bus, repo)
    RankingWorker(bus, repo)
    LlmWorker(bus, retrieval, evidence_hops=evidence_hops)
    notif = NotificationWorker(bus, sink=delivered.append)

    return Pipeline(
        bus=bus, repo=repo, ingestion=ingestion, retrieval=retrieval,
        notifications=notif.engine, delivered=delivered,
    )
