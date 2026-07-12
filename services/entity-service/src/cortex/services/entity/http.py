"""entity-service HTTP surface.

Health/ready/metrics come from the shared base app. The domain routes expose the
extractor synchronously: POST /api/v1/extract runs the same deterministic extraction the
Kafka worker runs, which makes the transform independently testable and callable without
the bus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cortex.contracts.payloads import RawEvent
from cortex.platform.http import Readiness, create_base_app
from cortex.services.entity.extractors import extract
from cortex.services.entity.worker import EntityWorker

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI


def create_app(worker: EntityWorker | None = None, *, readiness: Readiness | None = None) -> "FastAPI":
    from fastapi import Body

    app = create_base_app("entity-service", readiness=readiness)

    @app.post("/api/v1/extract", tags=["entity"], summary="Extract typed entities from a raw event")
    def extract_entities(raw: RawEvent = Body(...)) -> dict:
        extracted = extract(raw)
        return {
            "data": extracted.model_dump(mode="json"),
            "meta": {"nodes": len(extracted.nodes), "edges": len(extracted.edges)},
            "errors": [],
        }

    @app.get("/api/v1/stats", tags=["entity"], summary="Worker throughput counters")
    def stats() -> dict:
        return {
            "data": {
                "events_processed": worker.processed if worker else 0,
                "nodes_extracted": worker.nodes_extracted if worker else 0,
            },
            "meta": {},
            "errors": [],
        }

    return app
