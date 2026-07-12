"""ranking-service HTTP surface.

POST /api/v1/score scores a node on demand (the same UrgencyScorer the consumer runs over
graph.changes), returning the score, confidence, and the feature vector that produced it.
GET /api/v1/weights exposes the model weights for transparency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cortex.graph_sdk.repository import GraphRepository
from cortex.platform.http import Readiness, create_base_app
from cortex.services.ranking.scoring import UrgencyScorer

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI


def create_app(
    repo: GraphRepository,
    scorer: UrgencyScorer,
    *,
    hops: int = 2,
    readiness: Readiness | None = None,
) -> "FastAPI":
    from fastapi import Body, Header, HTTPException

    app = create_base_app("ranking-service", readiness=readiness)

    def _org(x_org_id: str | None) -> str:
        if not x_org_id:
            raise HTTPException(status_code=401, detail="missing org scope")
        return x_org_id

    @app.post("/api/v1/score", tags=["ranking"], summary="Score a node's urgency on demand")
    def score(body: dict = Body(...), x_org_id: str | None = Header(default=None)) -> dict:
        org = _org(x_org_id)
        node_id = str(body.get("node_id", ""))
        anchor = repo.get_node(org_id=org, node_id=node_id)
        if anchor is None:
            raise HTTPException(status_code=404, detail="node not found")
        nodes, edges = repo.neighborhood(org_id=org, node_id=node_id, hops=int(body.get("hops", hops)))
        result = scorer.score(anchor, nodes, edges)
        return {
            "data": {
                "node_id": result.node_id,
                "score": result.score,
                "confidence": result.confidence,
                "features": result.features,
            },
            "meta": {"org_id": org},
            "errors": [],
        }

    @app.get("/api/v1/weights", tags=["ranking"], summary="Urgency model weights")
    def weights() -> dict:
        return {"data": scorer.weights, "meta": {}, "errors": []}

    return app
