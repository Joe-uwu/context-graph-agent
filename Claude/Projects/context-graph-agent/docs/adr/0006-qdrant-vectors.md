# 0006 — Qdrant for vector retrieval

Status: Accepted

## Context

Hybrid retrieval needs an approximate-nearest-neighbor arm over embeddings of nodes, subgraphs, and documents, filtered by tenant and metadata. It must support fast filtered ANN (org isolation is non-negotiable, so the filter cannot be a post-hoc scan) and upsert-by-id as embeddings are recomputed on graph change.

## Decision

Use Qdrant as the vector store. Store three embedding scopes (node, subgraph, document) keyed by node id with `org_id` and metadata in the payload for filtered search. Version vectors by embedding-model id so a model upgrade re-embeds lazily. Only `retrieval-service` writes it.

## Consequences

Filtered ANN is a first-class Qdrant operation, so tenant scoping happens inside the search rather than after it. Payload filtering covers the metadata arm cheaply. It runs in Docker Compose for local dev and clusters for production. The cost is another store to operate and keeping vectors consistent with the graph (handled by re-embedding on `graph.changes`). Vectors can lag the graph briefly; retrieval tolerates this because the graph arm, not the vector arm, is the lead signal.

## Alternatives considered

pgvector — attractive for consolidating onto Postgres, but filtered-ANN performance and payload flexibility are weaker at the scale targeted. Pinecone/Weaviate — Pinecone is managed-only (no local-dev parity), Weaviate is comparable but heavier to run; Qdrant chosen for local/prod parity and simple filtered search. Storing vectors in Neo4j — rejected; Neo4j's vector index is serviceable but keeping ANN in a purpose-built store keeps the graph engine focused on traversal.
