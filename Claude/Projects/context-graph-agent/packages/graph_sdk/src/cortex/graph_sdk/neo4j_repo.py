"""Neo4j GraphRepository — the production graph store (ADR-0005).

Same interface as InMemoryGraphRepository. Writes are idempotent MERGE on
(org_id, natural_key); edges are closed by setting valid_to rather than deleted; every
query is scoped by org_id. Requires the `neo4j` extra and a running Neo4j.
"""

from __future__ import annotations

from datetime import datetime, timezone

from cortex.contracts.enums import EdgeType, NodeLabel
from cortex.graph_sdk.models import Edge, Node
from cortex.graph_sdk.repository import GraphRepository
from cortex.platform.ids import new_id

CONSTRAINTS = [
    # One uniqueness constraint per label; abbreviated here to the core labels.
    "CREATE CONSTRAINT person_key IF NOT EXISTS FOR (n:Person) REQUIRE (n.org_id, n.natural_key) IS UNIQUE",
    "CREATE CONSTRAINT service_key IF NOT EXISTS FOR (n:Service) REQUIRE (n.org_id, n.natural_key) IS UNIQUE",
    "CREATE CONSTRAINT pr_key IF NOT EXISTS FOR (n:PullRequest) REQUIRE (n.org_id, n.natural_key) IS UNIQUE",
    "CREATE CONSTRAINT ticket_key IF NOT EXISTS FOR (n:Ticket) REQUIRE (n.org_id, n.natural_key) IS UNIQUE",
    "CREATE CONSTRAINT incident_key IF NOT EXISTS FOR (n:Incident) REQUIRE (n.org_id, n.natural_key) IS UNIQUE",
    "CREATE CONSTRAINT deployment_key IF NOT EXISTS FOR (n:Deployment) REQUIRE (n.org_id, n.natural_key) IS UNIQUE",
    "CREATE INDEX node_org IF NOT EXISTS FOR (n:Entity) ON (n.org_id)",
]


class Neo4jGraphRepository(GraphRepository):
    def __init__(self, uri: str, user: str, password: str) -> None:
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Neo4jGraphRepository requires the 'neo4j' extra") from exc
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def init_schema(self) -> None:  # pragma: no cover - requires live db
        with self._driver.session() as s:
            for stmt in CONSTRAINTS:
                s.run(stmt)

    def upsert_node(
        self, *, org_id, label: NodeLabel, natural_key, source,
        properties, provenance_event_id, confidence=1.0,
    ) -> Node:  # pragma: no cover - requires live db
        now = datetime.now(timezone.utc)
        query = (
            f"MERGE (n:Entity:{label.value} {{org_id: $org_id, natural_key: $key}}) "
            "ON CREATE SET n.id=$id, n.source=$source, n.created_at=$now, "
            "  n.confidence=$conf, n.provenance=[$evt], n.urgency=0.0 "
            "ON MATCH SET n.provenance = "
            "  CASE WHEN $evt IN n.provenance THEN n.provenance ELSE n.provenance + $evt END, "
            "  n.confidence = CASE WHEN $conf > n.confidence THEN $conf ELSE n.confidence END "
            "SET n += $props, n.updated_at=$now, n.label=$label "
            "RETURN n"
        )
        with self._driver.session() as s:
            rec = s.run(
                query, org_id=org_id, key=natural_key, id=new_id("nd"), source=source,
                now=now.isoformat(), conf=confidence, evt=provenance_event_id,
                props=properties, label=label.value,
            ).single()
            return _to_node(rec["n"])

    def upsert_edge(
        self, *, org_id, type: EdgeType, from_id, to_id, confidence,
        discovered_by, provenance_event_id, properties=None,
    ) -> Edge:  # pragma: no cover - requires live db
        now = datetime.now(timezone.utc)
        query = (
            "MATCH (a:Entity {org_id:$org_id, id:$from_id}), (b:Entity {org_id:$org_id, id:$to_id}) "
            f"MERGE (a)-[r:{type.value} {{valid_to: null}}]->(b) "
            "ON CREATE SET r.id=$id, r.confidence=$conf, r.discovered_by=$db, "
            "  r.provenance=[$evt], r.valid_from=$now, r.properties=$props "
            "ON MATCH SET r.provenance = "
            "  CASE WHEN $evt IN r.provenance THEN r.provenance ELSE r.provenance + $evt END, "
            "  r.confidence = CASE WHEN $conf > r.confidence THEN $conf ELSE r.confidence END "
            "RETURN r, a.id AS from_id, b.id AS to_id"
        )
        with self._driver.session() as s:
            rec = s.run(
                query, org_id=org_id, from_id=from_id, to_id=to_id, id=new_id("eg"),
                conf=confidence, db=discovered_by, evt=provenance_event_id,
                now=now.isoformat(), props=properties or {},
            ).single()
            return _to_edge(rec["r"], org_id, type, rec["from_id"], rec["to_id"])

    def close_edge(self, *, org_id, edge_id) -> None:  # pragma: no cover
        with self._driver.session() as s:
            s.run(
                "MATCH ()-[r {id:$eid, org_id:$org_id}]->() SET r.valid_to=$now",
                eid=edge_id, org_id=org_id, now=datetime.now(timezone.utc).isoformat(),
            )

    def set_urgency(self, *, org_id, node_id, score, features) -> None:  # pragma: no cover
        with self._driver.session() as s:
            s.run(
                "MATCH (n:Entity {org_id:$org_id, id:$id}) "
                "SET n.urgency=$score, n.urgency_features=$features, n.scored_at=$now",
                org_id=org_id, id=node_id, score=score, features=features,
                now=datetime.now(timezone.utc).isoformat(),
            )

    def get_node(self, *, org_id, node_id) -> Node | None:  # pragma: no cover
        with self._driver.session() as s:
            rec = s.run(
                "MATCH (n:Entity {org_id:$org_id, id:$id}) RETURN n", org_id=org_id, id=node_id
            ).single()
            return _to_node(rec["n"]) if rec else None

    def find_node(self, *, org_id, natural_key) -> Node | None:  # pragma: no cover
        with self._driver.session() as s:
            rec = s.run(
                "MATCH (n:Entity {org_id:$org_id, natural_key:$key}) RETURN n",
                org_id=org_id, key=natural_key,
            ).single()
            return _to_node(rec["n"]) if rec else None

    def edges_of(self, *, org_id, node_id, current_only=True) -> list[Edge]:  # pragma: no cover
        cond = "AND r.valid_to IS NULL " if current_only else ""
        with self._driver.session() as s:
            recs = s.run(
                "MATCH (a:Entity {org_id:$org_id, id:$id})-[r]-(b) "
                f"WHERE b.org_id=$org_id {cond}"
                "RETURN r, type(r) AS t, startNode(r).id AS f, endNode(r).id AS e",
                org_id=org_id, id=node_id,
            )
            return [_to_edge(r["r"], org_id, EdgeType(r["t"]), r["f"], r["e"]) for r in recs]

    def neighborhood(
        self, *, org_id, node_id, hops=2, edge_types=None, current_only=True,
    ) -> tuple[list[Node], list[Edge]]:  # pragma: no cover
        rels = f":{'|'.join(t.value for t in edge_types)}" if edge_types else ""
        cond = "WHERE ALL(r IN relationships(p) WHERE r.valid_to IS NULL) " if current_only else ""
        with self._driver.session() as s:
            recs = s.run(
                f"MATCH p=(a:Entity {{org_id:$org_id, id:$id}})-[{rels}*0..{hops}]-(b:Entity) "
                f"{cond}RETURN nodes(p) AS ns, relationships(p) AS rs",
                org_id=org_id, id=node_id,
            )
            nodes: dict[str, Node] = {}
            edges: dict[str, Edge] = {}
            for r in recs:
                for n in r["ns"]:
                    node = _to_node(n)
                    nodes[node.id] = node
                for rel in r["rs"]:
                    edge = _to_edge(rel, org_id, EdgeType(rel.type), rel.start_node["id"], rel.end_node["id"])
                    edges[edge.id] = edge
            return list(nodes.values()), list(edges.values())

    def top_by_urgency(self, *, org_id, limit=20, min_score=0.0) -> list[Node]:  # pragma: no cover
        with self._driver.session() as s:
            recs = s.run(
                "MATCH (n:Entity {org_id:$org_id}) WHERE n.urgency >= $min "
                "RETURN n ORDER BY n.urgency DESC LIMIT $limit",
                org_id=org_id, min=min_score, limit=limit,
            )
            return [_to_node(r["n"]) for r in recs]

    def all_nodes(self, *, org_id) -> list[Node]:  # pragma: no cover
        with self._driver.session() as s:
            recs = s.run("MATCH (n:Entity {org_id:$org_id}) RETURN n", org_id=org_id)
            return [_to_node(r["n"]) for r in recs]


def _to_node(raw) -> Node:  # pragma: no cover - requires live db
    d = dict(raw)
    return Node(
        id=d["id"], org_id=d["org_id"], label=NodeLabel(d["label"]), natural_key=d["natural_key"],
        source=d.get("source", "derived"), properties=d.get("properties", {}),
        provenance=d.get("provenance", []), urgency=d.get("urgency", 0.0),
        urgency_features=d.get("urgency_features", {}), confidence=d.get("confidence", 1.0),
    )


def _to_edge(raw, org_id, type_: EdgeType, from_id, to_id) -> Edge:  # pragma: no cover
    d = dict(raw)
    return Edge(
        id=d["id"], org_id=org_id, type=type_, from_id=from_id, to_id=to_id,
        confidence=d.get("confidence", 1.0), discovered_by=d.get("discovered_by", "rule"),
        properties=d.get("properties", {}), provenance=d.get("provenance", []),
    )
