"""graph-service HTTP surface.

Read access to the context graph this service writes: fetch a node with its edges, pull
a k-hop neighborhood, and read per-tenant graph size. All routes are org-scoped via the
X-Org-Id header (a real deployment resolves org_id from the caller's JWT).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cortex.graph_sdk.repository import GraphRepository
from cortex.platform.http import Readiness, create_base_app

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI


def create_app(repo: GraphRepository, *, readiness: Readiness | None = None) -> "FastAPI":
    from fastapi import Header, HTTPException, Query

    app = create_base_app("graph-service", readiness=readiness)

    def _org(x_org_id: str | None) -> str:
        if not x_org_id:
            raise HTTPException(status_code=401, detail="missing org scope")
        return x_org_id

    @app.get("/api/v1/nodes/{node_id}", tags=["graph"], summary="Node with its current edges")
    def get_node(node_id: str, x_org_id: str | None = Header(default=None)) -> dict:
        org = _org(x_org_id)
        node = repo.get_node(org_id=org, node_id=node_id)
        if node is None:
            raise HTTPException(status_code=404, detail="node not found")
        edges = repo.edges_of(org_id=org, node_id=node_id)
        return {
            "data": {
                "node": node.model_dump(mode="json"),
                "edges": [e.model_dump(mode="json") for e in edges],
            },
            "meta": {"org_id": org},
            "errors": [],
        }

    @app.get(
        "/api/v1/nodes/{node_id}/neighborhood", tags=["graph"],
        summary="k-hop subgraph around a node",
    )
    def neighborhood(
        node_id: str,
        hops: int = Query(2, ge=1, le=4),
        x_org_id: str | None = Header(default=None),
    ) -> dict:
        org = _org(x_org_id)
        if repo.get_node(org_id=org, node_id=node_id) is None:
            raise HTTPException(status_code=404, detail="node not found")
        nodes, edges = repo.neighborhood(org_id=org, node_id=node_id, hops=hops)
        return {
            "data": {
                "nodes": [n.model_dump(mode="json") for n in nodes],
                "edges": [e.model_dump(mode="json") for e in edges],
            },
            "meta": {"org_id": org, "hops": hops},
            "errors": [],
        }

    @app.get("/api/v1/stats", tags=["graph"], summary="Per-tenant graph size")
    def stats(x_org_id: str | None = Header(default=None)) -> dict:
        org = _org(x_org_id)
        nodes = repo.all_nodes(org_id=org)
        by_label: dict[str, int] = {}
        for n in nodes:
            by_label[n.label.value] = by_label.get(n.label.value, 0) + 1
        return {
            "data": {"nodes": len(nodes), "by_label": by_label},
            "meta": {"org_id": org},
            "errors": [],
        }

    return app
