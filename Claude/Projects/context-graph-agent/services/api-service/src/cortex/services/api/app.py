"""FastAPI application factory.

Routes are org-scoped (a real deployment resolves org_id from the JWT; here it comes from
a header for demoability). The app is constructed around injected stores so it can serve
the in-memory pipeline in the demo and the real stores in production without code change.
"""

from __future__ import annotations

from typing import Any

from cortex.graph_sdk.repository import GraphRepository
from cortex.platform.http import Readiness, create_base_app
from cortex.services.notification.engine import NotificationEngine
from cortex.services.retrieval.service import RetrievalService

try:
    from fastapi import FastAPI, Header, HTTPException, Query
except ImportError as exc:  # pragma: no cover - optional dependency
    raise RuntimeError("api-service requires the 'api' extra (fastapi, uvicorn)") from exc

from cortex.platform.observability import METRICS


def create_app(
    repo: GraphRepository,
    retrieval: RetrievalService,
    notifications: NotificationEngine,
    *,
    readiness: Readiness | None = None,
) -> "FastAPI":
    # The gateway shares the same base surface as every other service: /health, /ready,
    # /metrics, and request metrics come from create_base_app; the API routes are added on
    # top. The client-facing tenant scope still comes from the X-Org-Id header.
    app = create_base_app("api-service", readiness=readiness)

    def _org(x_org_id: str | None) -> str:
        if not x_org_id:
            raise HTTPException(status_code=401, detail="missing org scope")
        return x_org_id

    def _envelope(data: Any, org_id: str) -> dict:
        return {"data": data, "meta": {"org_id": org_id}, "errors": []}

    @app.get("/api/v1/risk/top", tags=["api"])
    def top_risks(
        limit: int = Query(20, ge=1, le=100),
        min_score: float = Query(0.0, ge=0.0, le=1.0),
        x_org_id: str | None = Header(default=None),
    ) -> dict:
        org = _org(x_org_id)
        METRICS.inc("api_risk_top_requests_total")
        nodes = repo.top_by_urgency(org_id=org, limit=limit, min_score=min_score)
        data = [
            {"id": n.id, "label": n.label.value, "display": n.display(),
             "urgency": n.urgency, "features": n.urgency_features}
            for n in nodes
        ]
        return _envelope(data, org)

    @app.get("/api/v1/graph/nodes/{node_id}")
    def get_node(node_id: str, x_org_id: str | None = Header(default=None)) -> dict:
        org = _org(x_org_id)
        node = repo.get_node(org_id=org, node_id=node_id)
        if node is None:
            raise HTTPException(status_code=404, detail="node not found")
        edges = repo.edges_of(org_id=org, node_id=node_id)
        return _envelope({
            "node": node.model_dump(mode="json"),
            "edges": [e.model_dump(mode="json") for e in edges],
        }, org)

    @app.get("/api/v1/graph/nodes/{node_id}/neighborhood")
    def neighborhood(
        node_id: str, hops: int = Query(2, ge=1, le=4),
        x_org_id: str | None = Header(default=None),
    ) -> dict:
        org = _org(x_org_id)
        nodes, edges = repo.neighborhood(org_id=org, node_id=node_id, hops=hops)
        return _envelope({
            "nodes": [n.model_dump(mode="json") for n in nodes],
            "edges": [e.model_dump(mode="json") for e in edges],
        }, org)

    @app.post("/api/v1/search")
    def search(body: dict, x_org_id: str | None = Header(default=None)) -> dict:
        org = _org(x_org_id)
        query = str(body.get("query", ""))
        hits = retrieval.search(org_id=org, query=query, limit=int(body.get("limit", 20)))
        data = [{"id": n.id, "label": n.label.value, "display": n.display()} for n in hits]
        return _envelope(data, org)

    @app.get("/api/v1/notifications")
    def list_notifications(x_org_id: str | None = Header(default=None)) -> dict:
        org = _org(x_org_id)
        data = [
            {"id": n.id, "node_id": n.node_id, "channel": n.channel.value, "title": n.title,
             "body": n.body, "risk_score": n.risk_score, "confidence": n.confidence,
             "recipients": n.recipients}
            for n in notifications.feed
        ]
        return _envelope(data, org)

    return app
