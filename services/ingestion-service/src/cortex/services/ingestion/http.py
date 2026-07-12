"""ingestion-service HTTP surface.

Health/ready/metrics from the base app, plus control/introspection routes: list the
registered connectors, trigger a backfill, and read throughput counters.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from cortex.platform.http import Readiness, create_base_app
from cortex.platform.observability import METRICS
from cortex.services.ingestion.connectors.github.webhooks import parse_event, verify_signature
from cortex.services.ingestion.worker import IngestionWorker

try:
    # Imported at module scope so FastAPI can resolve the Request annotation on the webhook
    # route (from __future__ import annotations makes hints strings resolved via globals).
    from fastapi import HTTPException, Request
except ImportError as exc:  # pragma: no cover - optional dependency
    raise RuntimeError("ingestion-service requires the 'api' extra (fastapi, uvicorn)") from exc

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI


def create_app(
    worker: IngestionWorker, *, webhook_secret: str = "", readiness: Readiness | None = None
) -> "FastAPI":
    app = create_base_app("ingestion-service", readiness=readiness)

    @app.get("/api/v1/connectors", tags=["ingestion"], summary="Registered source connectors")
    def connectors() -> dict:
        return {"data": worker.connector_names, "meta": {}, "errors": []}

    @app.post("/api/v1/sync", tags=["ingestion"], summary="Run a backfill of every connector")
    def sync() -> dict:
        published = worker.run_initial_sync()
        return {"data": {"published": published}, "meta": {}, "errors": []}

    @app.get("/api/v1/stats", tags=["ingestion"], summary="Ingestion throughput counters")
    def stats() -> dict:
        return {
            "data": {
                "connectors": len(worker.connector_names),
                "events_published": worker.published,
            },
            "meta": {},
            "errors": [],
        }

    @app.post("/webhooks/github", tags=["ingestion"], summary="GitHub webhook receiver")
    async def github_webhook(request: Request) -> dict:
        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256")
        if not webhook_secret or not verify_signature(webhook_secret, body, signature):
            METRICS.inc("cortex_github_webhook_rejected_total", service="ingestion-service")
            raise HTTPException(status_code=401, detail="invalid or missing signature")
        event_type = request.headers.get("X-GitHub-Event", "")
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="invalid JSON body") from exc
        events = parse_event(event_type, payload)
        published = worker.ingest(events)
        METRICS.inc(
            "cortex_github_webhook_events_total", float(published),
            service="ingestion-service", event=event_type or "unknown",
        )
        return {
            "data": {"event": event_type, "published": published},
            "meta": {"delivery": request.headers.get("X-GitHub-Delivery")},
            "errors": [],
        }

    return app
