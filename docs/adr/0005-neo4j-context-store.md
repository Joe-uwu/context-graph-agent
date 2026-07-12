# 0005 — Neo4j as the context graph store

Status: Accepted

## Context

The core data structure is a heterogeneous, densely connected graph of entities and typed relationships, queried by multi-hop traversal ("what deployment is blocked by an incident that affects a service touched by this PR"). The workload is traversal-heavy, the relationships carry properties (confidence, temporal validity, provenance), and the schema evolves as new sources add node and edge types.

## Decision

Use Neo4j as the graph store. Model relationships as first-class edges with properties. Enforce identity with `(org_id, natural_key)` uniqueness constraints per label, index for tenancy and common filters, and use a fulltext index for the keyword arm of retrieval. Access it only through `graph-service` (write) and the `graph-sdk` repository (read).

## Consequences

Multi-hop traversal is expressed directly in Cypher and executes without the join explosion a relational model would incur at depth. Edge properties give us provenance/confidence/temporal validity natively. Neo4j's maturity (constraints, fulltext, clustering) covers the operational needs. The costs: another datastore to run and back up, a query language the team must learn, and care required to keep hot traversals bounded (k-hop limits, edge-type weighting). Very large analytical sweeps are not Neo4j's strength — but those are not the workload; the workload is bounded local traversal, which it does well.

## Alternatives considered

A relational model with join tables — rejected because deep traversal degrades badly and the relationship-as-data model is awkward. A property graph on top of Postgres (Apache AGE) — plausible and keeps one fewer store, but less mature tooling for the traversal and fulltext needs. Amazon Neptune / TigerGraph — viable managed/alternative engines; Neo4j chosen for tooling maturity, local-dev ergonomics (runs in Compose), and Cypher familiarity. RDF triple stores — rejected as heavier than needed for a property-graph workload.
