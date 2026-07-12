# 0008 — Auth and multi-tenant isolation

Status: Accepted

## Context

Cortex holds a graph of an organization's private engineering activity. A cross-tenant leak — one org seeing another's incidents, people, or code activity — is the worst failure the system can have. Isolation must be structural, not a filter someone can forget to add.

## Decision

Every record in every store carries `org_id`. There is no unscoped query path: Neo4j constraints and indexes are keyed by `(org_id, ...)`, Qdrant searches are payload-filtered by `org_id`, Kafka topics are partitioned by `org_id`, and the `graph-sdk` repository requires an `org_id` argument so an unscoped query cannot be written by accident. Users authenticate with JWTs carrying `org_id`, `sub`, and `roles` (`viewer`, `member`, `admin`, `owner`); `api-service` authorizes at the edge and re-scopes at the data layer. Source OAuth uses PKCE where the provider supports public clients; no third-party secret is stored client-side.

## Consequences

Tenant isolation is enforced in the type system and the schema, not left to reviewer vigilance — the repository will not compile a query without an org scope. Defense in depth (edge auth + data-layer scoping) means one missed check is not a breach. Role granularity supports read-only viewers and admin connector management. The cost is that `org_id` threads through every layer and every query, which is verbose but deliberately unavoidable.

## Alternatives considered

Database-per-tenant — the strongest isolation, but operationally heavy at many tenants and it complicates the shared graph tooling; revisit if a large enterprise customer requires physical separation. Row-level filtering applied only at the API layer — rejected because a single missed filter leaks data; scoping must be at the store. Trusting application-level checks alone without schema-level constraints — rejected for the same reason.
