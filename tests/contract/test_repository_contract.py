"""GraphRepository contract: the same behavioural suite runs against both the in-memory
implementation and a real Neo4j.

The ``memory`` parameter always runs. The ``neo4j`` parameter runs only when
``CORTEX_NEO4J_URI`` points at a reachable database (CI provides one via a service
container); otherwise it skips. This is what guarantees the Neo4j adapter matches the
reference semantics rather than merely "having the same method names".
"""

from __future__ import annotations

import os

import pytest
from cortex.contracts.enums import EdgeType, NodeLabel
from cortex.graph_sdk.memory import InMemoryGraphRepository
from cortex.graph_sdk.repository import GraphRepository

ORG = "org_test"
OTHER = "org_other"


def _neo4j_or_skip() -> GraphRepository:
    uri = os.environ.get("CORTEX_NEO4J_URI")
    if not uri:
        pytest.skip("CORTEX_NEO4J_URI not set")
    pytest.importorskip("neo4j")
    from cortex.graph_sdk.neo4j_repo import Neo4jGraphRepository

    repo = Neo4jGraphRepository(
        uri,
        os.environ.get("CORTEX_NEO4J_USER", "neo4j"),
        os.environ.get("CORTEX_NEO4J_PASSWORD", "password"),
    )
    try:
        repo.verify_connectivity()
    except Exception as exc:  # noqa: BLE001 - any driver error means "not available here"
        pytest.skip(f"neo4j unreachable: {exc}")
    repo.init_schema()
    with repo._driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    return repo


@pytest.fixture(params=["memory", "neo4j"])
def repo(request) -> GraphRepository:
    if request.param == "memory":
        return InMemoryGraphRepository()
    return _neo4j_or_skip()


def _node(repo, key, *, label=NodeLabel.SERVICE, source="github", props=None,
          evt="evt-1", conf=1.0, org=ORG):
    return repo.upsert_node(
        org_id=org, label=label, natural_key=key, source=source,
        properties=props or {}, provenance_event_id=evt, confidence=conf,
    )


def test_upsert_node_is_idempotent_and_merges(repo: GraphRepository):
    a = _node(repo, "svc-billing", props={"name": "billing"}, evt="e1", conf=0.5)
    b = _node(repo, "svc-billing", props={"criticality": "tier0"}, evt="e2", conf=0.9)
    assert a.id == b.id
    got = repo.get_node(org_id=ORG, node_id=a.id)
    assert got is not None
    assert got.properties == {"name": "billing", "criticality": "tier0"}
    assert set(got.provenance) == {"e1", "e2"}
    assert got.confidence == 0.9


def test_find_node(repo: GraphRepository):
    n = _node(repo, "svc-x")
    assert repo.find_node(org_id=ORG, natural_key="svc-x").id == n.id
    assert repo.find_node(org_id=ORG, natural_key="missing") is None


def test_org_scoping(repo: GraphRepository):
    n = _node(repo, "svc-a", org=ORG)
    assert repo.get_node(org_id=OTHER, node_id=n.id) is None
    assert repo.all_nodes(org_id=OTHER) == []
    assert len(repo.all_nodes(org_id=ORG)) == 1


def test_neighborhood_k_hops(repo: GraphRepository):
    a = _node(repo, "a")
    b = _node(repo, "b")
    c = _node(repo, "c")
    repo.upsert_edge(org_id=ORG, type=EdgeType.DEPENDS_ON, from_id=a.id, to_id=b.id,
                     confidence=1.0, discovered_by="rule", provenance_event_id="e1")
    repo.upsert_edge(org_id=ORG, type=EdgeType.DEPENDS_ON, from_id=b.id, to_id=c.id,
                     confidence=1.0, discovered_by="rule", provenance_event_id="e2")

    assert len(repo.edges_of(org_id=ORG, node_id=a.id)) == 1
    assert len(repo.edges_of(org_id=ORG, node_id=b.id)) == 2

    nodes1, edges1 = repo.neighborhood(org_id=ORG, node_id=a.id, hops=1)
    assert {n.natural_key for n in nodes1} == {"a", "b"}
    assert len(edges1) == 1

    nodes2, _ = repo.neighborhood(org_id=ORG, node_id=a.id, hops=2)
    assert {n.natural_key for n in nodes2} == {"a", "b", "c"}


def test_neighborhood_missing_anchor(repo: GraphRepository):
    assert repo.neighborhood(org_id=ORG, node_id="nope", hops=2) == ([], [])


def test_edge_upsert_idempotent(repo: GraphRepository):
    a = _node(repo, "a")
    b = _node(repo, "b")
    e1 = repo.upsert_edge(org_id=ORG, type=EdgeType.BLOCKS, from_id=a.id, to_id=b.id,
                          confidence=0.5, discovered_by="rule", provenance_event_id="e1")
    e2 = repo.upsert_edge(org_id=ORG, type=EdgeType.BLOCKS, from_id=a.id, to_id=b.id,
                          confidence=0.8, discovered_by="rule", provenance_event_id="e2")
    assert e1.id == e2.id
    edges = repo.edges_of(org_id=ORG, node_id=a.id)
    assert len(edges) == 1
    assert set(edges[0].provenance) == {"e1", "e2"}
    assert edges[0].confidence == 0.8


def test_temporal_close_then_reopen(repo: GraphRepository):
    a = _node(repo, "a")
    b = _node(repo, "b")
    e = repo.upsert_edge(org_id=ORG, type=EdgeType.TOUCHES, from_id=a.id, to_id=b.id,
                         confidence=1.0, discovered_by="rule", provenance_event_id="e1")
    repo.close_edge(org_id=ORG, edge_id=e.id)
    assert repo.edges_of(org_id=ORG, node_id=a.id, current_only=True) == []
    assert len(repo.edges_of(org_id=ORG, node_id=a.id, current_only=False)) == 1

    e2 = repo.upsert_edge(org_id=ORG, type=EdgeType.TOUCHES, from_id=a.id, to_id=b.id,
                          confidence=1.0, discovered_by="rule", provenance_event_id="e2")
    assert e2.id != e.id  # a new current edge, history preserved
    assert len(repo.edges_of(org_id=ORG, node_id=a.id, current_only=True)) == 1
    assert len(repo.edges_of(org_id=ORG, node_id=a.id, current_only=False)) == 2


def test_urgency_ranking(repo: GraphRepository):
    a = _node(repo, "a")
    b = _node(repo, "b")
    _node(repo, "c")
    repo.set_urgency(org_id=ORG, node_id=a.id, score=0.9, features={"incident_severity": 1.0})
    repo.set_urgency(org_id=ORG, node_id=b.id, score=0.4, features={})
    top = repo.top_by_urgency(org_id=ORG, limit=10, min_score=0.5)
    assert [n.id for n in top] == [a.id]
    got = repo.get_node(org_id=ORG, node_id=a.id)
    assert got.urgency == 0.9
    assert got.urgency_features == {"incident_severity": 1.0}
