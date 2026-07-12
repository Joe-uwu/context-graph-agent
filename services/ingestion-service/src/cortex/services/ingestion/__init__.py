"""ingestion-service: the connector runtime.

Every source implements the Connector protocol (initial_sync / incremental_sync /
stream) with shared machinery for dedup, retry, and rate limiting. Each source ships a
real connector and a mock twin behind the same interface (ADR-0003). The worker turns
connector output into normalized raw.events.
"""
