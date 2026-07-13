// Cortex context-graph schema for Neo4j 5.x.
//
// This mirrors Neo4jGraphRepository.init_schema() (packages/graph_sdk/.../neo4j_repo.py),
// which applies the same statements on service start-up. Kept here so the schema can also
// be applied manually (cypher-shell -f) or reviewed independently. All statements are
// idempotent (IF NOT EXISTS).
//
// Every node carries the :Entity label plus its specific label (e.g. :Service, :Incident).
// Uniqueness is enforced on (org_id, natural_key) so upserts MERGE rather than duplicate;
// tenant isolation and the urgency ranking query are backed by indexes.

// --- constraints ---
CREATE CONSTRAINT entity_key IF NOT EXISTS
  FOR (n:Entity) REQUIRE (n.org_id, n.natural_key) IS UNIQUE;

CREATE CONSTRAINT entity_id IF NOT EXISTS
  FOR (n:Entity) REQUIRE n.id IS UNIQUE;

// --- indexes ---
CREATE INDEX entity_org IF NOT EXISTS
  FOR (n:Entity) ON (n.org_id);

CREATE INDEX entity_urgency IF NOT EXISTS
  FOR (n:Entity) ON (n.org_id, n.urgency);
