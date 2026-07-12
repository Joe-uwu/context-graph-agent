"""retrieval-service HTTP surface.

Exposes the hybrid search and evidence-gathering the reasoning stage relies on:
POST /api/v1/search fuses the retrieval arms; GET /api/v1/evidence/{node_id} returns the
k-hop subgraph used as reasoning context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cortex.platform.http import Readiness, create_base_app
from cortex.platform.observability import METRICS
from cortex.services.retrieval.service import RetrievalService

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI


def create_app(
    retrieval: RetrievalService, *, default_hops: int = 2, readiness: Readiness | None = None
) -> "FastAPI":
    from fastapi import Body, Header, HTTPException, Query

    app = create_base_app("retrieval-service", readiness=readiness)

    def _org(x_org_id: str | None) -> str:
        if not x_org_id:
            raise HTTPException(status_code=401, detail="missing org scope")
        return x_org_id

    @app.post("/api/v1/search", tags=["retrieval"], summary="Hybrid graph+keyword search")
    def search(body: dict = Body(default={}), x_org_id: str | None = Header(default=None)) -> dict:
        org = _org(x_org_id)
        query = str(body.get("query", ""))
        limit = int(body.get("limit", 20))
        METRICS.inc("cortex_retrieval_queries_total", service="retrieval-service")
        hits = retrieval.search(org_id=org, query=query, limit=limit)
        data = [
            {"id": n.id, "label": n.label.value, "display": n.display(), "urgency": n.urgency}
            for n in hits
        ]
        return {"data": data, "meta": {"org_id": org, "query": query}, "errors": []}

    @app.get(
        "/api/v1/evidence/{node_id}", tags=["retrieval"],
        summary="k-hop evidence subgraph for a node",
    )
    def evidence(
        node_id: str,
        hops: int = Query(default_hops, ge=1, le=4),
        x_org_id: str | None = Header(default=None),
    ) -> dict:
        org = _org(x_org_id)
        ev = retrieval.gather_evidence(org_id=org, node_id=node_id, hops=hops)
        if ev is None:
            raise HTTPException(status_code=404, detail="node not found")
        return {
            "data": {
                "anchor": ev.anchor.model_dump(mode="json"),
                "nodes": [n.model_dump(mode="json") for n in ev.nodes],
                "edges": [e.model_dump(mode="json") for e in ev.edges],
            },
            "meta": {"org_id": org, "hops": hops},
            "errors": [],
        }

    return app
