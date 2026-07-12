# 0004 — Repository pattern and single-writer per store

Status: Accepted

## Context

Multiple services need to read the graph and the vector store. If several services also wrote them, concurrent writes would race, the schema would be enforced in many places, and it would be impossible to reason about how a node reached its current state.

## Decision

Each pipeline datastore has exactly one writer service: only `graph-service` writes Neo4j, only `retrieval-service` writes Qdrant, only `ingestion-service` writes sync cursors, only `notification-service` writes the notification store. Everyone else reads. All store access goes through a repository abstraction (`graph-sdk` for Neo4j, typed clients elsewhere) — services never build raw queries inline. `api-service`, which serves user actions, does not write pipeline stores directly; it emits `user.actions` events that the owning service applies, preserving the single-writer rule.

## Consequences

Write logic, schema enforcement, and invariants (idempotent MERGE, temporal edge closing) live in one place per store and are testable in isolation. Swapping a store implementation touches one repository, not every caller. Reasoning about state is tractable because there is one code path that produces it. The cost is an extra hop for user-initiated writes (action → event → owning service), which is acceptable given the system is already eventually consistent and it keeps the write model uniform.

## Alternatives considered

Shared data-access library that any service can write through — rejected because it distributes write responsibility and reintroduces the race and multi-enforcement problems the single-writer rule removes. Direct DB access from each service — rejected for the same reasons plus coupling every service to the store's schema.
