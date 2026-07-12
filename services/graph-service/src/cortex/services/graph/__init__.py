"""graph-service: resolve entities, discover relationships, write the graph.

The only writer of Neo4j (ADR-0004). Writes are idempotent MERGE by (org_id,
natural_key); edges no longer asserted are closed, not deleted; every write emits
graph.changes with the touched node ids so downstream scoring runs on just the delta.
"""
