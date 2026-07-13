"""Neo4j GraphRepository — the production graph store (ADR-0005).

Same behavioural contract as InMemoryGraphRepository (see tests/contract): idempotent
upsert on (org_id, natural_key), edges versioned by a ``current`` flag and closed with
``valid_to`` rather than deleted, every query scoped by org_id, k-hop subgraph traversal.

Neo4j properties must be primitives or arrays of primitives, so map-valued fields
(``properties``, ``urgency_features``, edge ``properties``) are stored as JSON strings and
rehydrated on read. Node property merges use an atomic read-modify-write inside one write
transaction; edge provenance/confidence merges are expressed directly in Cypher.

Requires the ``neo4j`` extra and a running Neo4j. The pure serialization/parse helpers at
the bottom are import-safe without the driver and are unit-tested directly.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from cortex.contracts.enums import DiscoveredBy, EdgeType, NodeLabel
from cortex.graph_sdk.models import Edge, Node
from cortex.graph_sdk.repository import GraphRepository
from cortex.platform.ids import new_id

# One composite uniqueness constraint on :Entity enforces idempotent upserts across every
# node label; a unique id constraint backs id lookups. Indexes back org scoping and the
# urgency ranking query.
CONSTRAINTS = [
    "CREATE CONSTRAINT entity_key IF NOT EXISTS "
    "FOR (n:Entity) REQUIRE (n.org_id, n.natural_key) IS UNIQUE",
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE",
]
INDEXES = [
    "CREATE INDEX entity_org IF NOT EXISTS FOR (n:Entity) ON (n.org_id)",
    "CREATE INDEX entity_urgency IF NOT EXISTS FOR (n:Entity) ON (n.org_id, n.urgency)",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Neo4jGraphRepository(GraphRepository):
    def __init__(self, uri: str, user: str, password: str) -> None:
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Neo4jGraphRepository requires the 'neo4j' extra") from exc
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    def verify_connectivity(self) -> None:
        self._driver.verify_connectivity()

    def init_schema(self) -> None:
        with self._driver.session() as session:
            for stmt in CONSTRAINTS + INDEXES:
                session.run(stmt)

    # --- writes ------------------------------------------------------------------

    def upsert_node(
        self, *, org_id: str, label: NodeLabel, natural_key: str, source: str,
        properties: dict, provenance_event_id: str, confidence: float = 1.0,
    ) -> Node:
        _require_label(label)
        now = _now_iso()

        def _tx(tx) -> Node:
            created = tx.run(
                f"MERGE (n:Entity {{org_id: $org_id, natural_key: $key}}) "
                f"ON CREATE SET n.id = $id, n:{label.value}, n.label = $label, "
                f"  n.source = $source, n.created_at = $now, n.updated_at = $now, "
                f"  n.confidence = $conf, n.provenance = [$evt], n.urgency = 0.0, "
                f"  n.urgency_features_json = '{{}}', n.properties_json = '{{}}' "
                f"RETURN n",
                org_id=org_id, key=natural_key, id=new_id("nd"), label=label.value,
                source=source, now=now, conf=confidence, evt=provenance_event_id,
            ).single()
            current = dict(created["n"])
            merged = {**_loads(current.get("properties_json")), **(properties or {})}
            provenance = list(current.get("provenance", []))
            if provenance_event_id not in provenance:
                provenance.append(provenance_event_id)
            best_conf = max(float(current.get("confidence", 1.0)), float(confidence))
            updated = tx.run(
                "MATCH (n:Entity {org_id: $org_id, id: $id}) "
                "SET n.properties_json = $props, n.provenance = $prov, "
                "  n.confidence = $conf, n.updated_at = $now "
                "RETURN n",
                org_id=org_id, id=current["id"], props=_dumps(merged),
                prov=provenance, conf=best_conf, now=now,
            ).single()
            return _node_from_props(dict(updated["n"]))

        with self._driver.session() as session:
            return session.execute_write(_tx)

    def upsert_edge(
        self, *, org_id: str, type: EdgeType, from_id: str, to_id: str, confidence: float,
        discovered_by: str, provenance_event_id: str, properties: dict | None = None,
    ) -> Edge:
        _require_edge_type(type)
        now = _now_iso()
        query = (
            "MATCH (a:Entity {org_id: $org_id, id: $from_id}), "
            "      (b:Entity {org_id: $org_id, id: $to_id}) "
            f"MERGE (a)-[r:{type.value} {{current: true}}]->(b) "
            "ON CREATE SET r.id = $id, r.confidence = $conf, r.discovered_by = $db, "
            "  r.provenance = [$evt], r.valid_from = $now, r.valid_to = null, "
            "  r.properties_json = $props "
            "ON MATCH SET r.provenance = CASE WHEN $evt IN r.provenance "
            "    THEN r.provenance ELSE r.provenance + [$evt] END, "
            "  r.confidence = CASE WHEN $conf > r.confidence THEN $conf ELSE r.confidence END "
            "RETURN r, startNode(r).id AS from_id, endNode(r).id AS to_id"
        )

        def _tx(tx) -> Edge:
            rec = tx.run(
                query, org_id=org_id, from_id=from_id, to_id=to_id, id=new_id("eg"),
                conf=confidence, db=discovered_by, evt=provenance_event_id, now=now,
                props=_dumps(properties or {}),
            ).single()
            return _edge_from_props(
                dict(rec["r"]), org_id, type, rec["from_id"], rec["to_id"]
            )

        with self._driver.session() as session:
            return session.execute_write(_tx)

    def close_edge(self, *, org_id: str, edge_id: str) -> None:
        with self._driver.session() as session:
            session.run(
                "MATCH (a:Entity {org_id: $org_id})-[r {id: $eid}]->(b) "
                "WHERE r.current SET r.current = false, r.valid_to = $now",
                org_id=org_id, eid=edge_id, now=_now_iso(),
            )

    def set_urgency(
        self, *, org_id: str, node_id: str, score: float, features: dict[str, float]
    ) -> None:
        with self._driver.session() as session:
            session.run(
                "MATCH (n:Entity {org_id: $org_id, id: $id}) "
                "SET n.urgency = $score, n.urgency_features_json = $features, n.scored_at = $now",
                org_id=org_id, id=node_id, score=score, features=_dumps(features), now=_now_iso(),
            )

    # --- reads -------------------------------------------------------------------

    def get_node(self, *, org_id: str, node_id: str) -> Node | None:
        with self._driver.session() as session:
            rec = session.run(
                "MATCH (n:Entity {org_id: $org_id, id: $id}) RETURN n",
                org_id=org_id, id=node_id,
            ).single()
            return _node_from_props(dict(rec["n"])) if rec else None

    def find_node(self, *, org_id: str, natural_key: str) -> Node | None:
        with self._driver.session() as session:
            rec = session.run(
                "MATCH (n:Entity {org_id: $org_id, natural_key: $key}) RETURN n",
                org_id=org_id, key=natural_key,
            ).single()
            return _node_from_props(dict(rec["n"])) if rec else None

    def edges_of(self, *, org_id: str, node_id: str, current_only: bool = True) -> list[Edge]:
        cond = "AND r.current " if current_only else ""
        with self._driver.session() as session:
            recs = session.run(
                "MATCH (a:Entity {org_id: $org_id, id: $id})-[r]-(b:Entity {org_id: $org_id}) "
                f"WHERE true {cond}"
                "RETURN r, type(r) AS t, startNode(r).id AS f, endNode(r).id AS e",
                org_id=org_id, id=node_id,
            )
            return [
                _edge_from_props(dict(r["r"]), org_id, EdgeType(r["t"]), r["f"], r["e"])
                for r in recs
            ]

    def neighborhood(
        self, *, org_id: str, node_id: str, hops: int = 2,
        edge_types: list[EdgeType] | None = None, current_only: bool = True,
    ) -> tuple[list[Node], list[Edge]]:
        if self.get_node(org_id=org_id, node_id=node_id) is None:
            return [], []
        rel_filter = ":" + "|".join(t.value for t in edge_types) if edge_types else ""
        cond = (
            "WHERE all(rel IN relationships(p) WHERE rel.current) " if current_only else ""
        )
        query = (
            f"MATCH p=(a:Entity {{org_id: $org_id, id: $id}})"
            f"-[r{rel_filter}*0..{int(hops)}]-(b:Entity {{org_id: $org_id}}) "
            f"{cond}RETURN nodes(p) AS ns, relationships(p) AS rs"
        )
        nodes: dict[str, Node] = {}
        edges: dict[str, Edge] = {}
        with self._driver.session() as session:
            for record in session.run(query, org_id=org_id, id=node_id):
                for raw in record["ns"]:
                    node = _node_from_props(dict(raw))
                    nodes[node.id] = node
                for rel in record["rs"]:
                    edge = _edge_from_props(
                        dict(rel), org_id, EdgeType(rel.type),
                        rel.start_node["id"], rel.end_node["id"],
                    )
                    edges[edge.id] = edge
        return list(nodes.values()), list(edges.values())

    def top_by_urgency(self, *, org_id: str, limit: int = 20, min_score: float = 0.0) -> list[Node]:
        with self._driver.session() as session:
            recs = session.run(
                "MATCH (n:Entity {org_id: $org_id}) WHERE n.urgency >= $min "
                "RETURN n ORDER BY n.urgency DESC LIMIT $limit",
                org_id=org_id, min=min_score, limit=int(limit),
            )
            return [_node_from_props(dict(r["n"])) for r in recs]

    def all_nodes(self, *, org_id: str) -> list[Node]:
        with self._driver.session() as session:
            recs = session.run("MATCH (n:Entity {org_id: $org_id}) RETURN n", org_id=org_id)
            return [_node_from_props(dict(r["n"])) for r in recs]


# --- pure helpers (import-safe without the neo4j driver; unit-tested directly) -----


def _dumps(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, default=str, sort_keys=True)


def _loads(value: Any) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _node_from_props(props: dict) -> Node:
    return Node(
        id=props["id"],
        org_id=props["org_id"],
        label=NodeLabel(props["label"]),
        natural_key=props["natural_key"],
        source=props.get("source", "derived"),
        properties=_loads(props.get("properties_json")),
        provenance=list(props.get("provenance", [])),
        urgency=float(props.get("urgency", 0.0)),
        urgency_features=_loads(props.get("urgency_features_json")),
        confidence=float(props.get("confidence", 1.0)),
    )


def _edge_from_props(props: dict, org_id: str, type_: EdgeType, from_id: str, to_id: str) -> Edge:
    valid_from = _parse_dt(props.get("valid_from")) or datetime.now(timezone.utc)
    return Edge(
        id=props["id"],
        org_id=org_id,
        type=type_,
        from_id=from_id,
        to_id=to_id,
        confidence=float(props.get("confidence", 1.0)),
        discovered_by=DiscoveredBy(props.get("discovered_by", "rule")),
        properties=_loads(props.get("properties_json")),
        provenance=list(props.get("provenance", [])),
        valid_from=valid_from,
        valid_to=_parse_dt(props.get("valid_to")),
    )


def _require_label(label: NodeLabel) -> None:
    # Labels/types are interpolated into Cypher (they cannot be parameters); constraining
    # them to the enum keeps that injection-safe.
    if not isinstance(label, NodeLabel):
        raise TypeError(f"label must be a NodeLabel, got {type(label)!r}")


def _require_edge_type(type_: EdgeType) -> None:
    if not isinstance(type_, EdgeType):
        raise TypeError(f"type must be an EdgeType, got {type(type_)!r}")
