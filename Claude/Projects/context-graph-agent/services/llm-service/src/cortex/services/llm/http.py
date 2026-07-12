"""llm-service HTTP surface.

POST /api/v1/reason gathers evidence for a node and runs the grounded reasoner, returning
the summary, explanation, recommended actions, and citations — the same output the
consumer emits on risk.scored, exposed for on-demand inspection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cortex.platform.http import Readiness, create_base_app
from cortex.services.llm.reasoning import Reasoner
from cortex.services.retrieval.service import RetrievalService

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI


def create_app(
    retrieval: RetrievalService,
    reasoner: Reasoner,
    *,
    evidence_hops: int = 3,
    readiness: Readiness | None = None,
) -> "FastAPI":
    from fastapi import Body, Header, HTTPException

    app = create_base_app("llm-service", readiness=readiness)

    def _org(x_org_id: str | None) -> str:
        if not x_org_id:
            raise HTTPException(status_code=401, detail="missing org scope")
        return x_org_id

    @app.post("/api/v1/reason", tags=["llm"], summary="Reason over a node's evidence subgraph")
    def reason(body: dict = Body(...), x_org_id: str | None = Header(default=None)) -> dict:
        org = _org(x_org_id)
        node_id = str(body.get("node_id", ""))
        hops = int(body.get("hops", evidence_hops))
        evidence = retrieval.gather_evidence(org_id=org, node_id=node_id, hops=hops)
        if evidence is None:
            raise HTTPException(status_code=404, detail="node not found")
        risk_score = float(body.get("risk_score", evidence.anchor.urgency))
        reasoning = reasoner.reason(evidence, risk_score)
        return {"data": reasoning.model_dump(mode="json"), "meta": {"org_id": org}, "errors": []}

    return app
