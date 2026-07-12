"""retrieval-service process entrypoint.

Consumes graph.changes to keep the vector index current (no-op index by default until a
Qdrant-backed VectorIndex is wired in) and serves hybrid retrieval + evidence gathering
over HTTP to llm-service and api-service.
"""

from __future__ import annotations

from cortex.contracts import Event, Topic
from cortex.platform.http import Readiness, serve
from cortex.platform.logging import get_logger
from cortex.platform.observability import METRICS
from cortex.platform.runtime import build_bus, build_graph_repo
from cortex.services.retrieval.config import GROUP, SERVICE_NAME, RetrievalSettings
from cortex.services.retrieval.http import create_app
from cortex.services.retrieval.service import RetrievalService

log = get_logger("cortex.retrieval")


def main() -> None:
    settings = RetrievalSettings()
    bus = build_bus(settings, client_id=GROUP)
    repo = build_graph_repo(settings)
    retrieval = RetrievalService(repo)

    def on_change(event: Event) -> None:
        METRICS.inc("cortex_events_processed_total", service="retrieval-service")
        log.info("re-embed", extra={"extra_fields": {"event_id": event.event_id}})

    bus.subscribe(Topic.GRAPH_CHANGES, on_change, group=GROUP)

    readiness = Readiness()
    app = create_app(retrieval, default_hops=settings.evidence_hops, readiness=readiness)
    serve(app, settings, service_name=SERVICE_NAME, bus=bus, group=GROUP, readiness=readiness)


if __name__ == "__main__":
    main()
