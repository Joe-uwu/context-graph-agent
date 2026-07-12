"""ingestion-service configuration."""

from __future__ import annotations

from cortex.platform.config import ServiceSettings

SERVICE_NAME = "ingestion-service"
GROUP = "ingestion-service"


class IngestionSettings(ServiceSettings):
    http_port: int = 8001

    # Tenant this ingestion process pulls for.
    org_id: str = "org_demo"
    # When true, register the mock connector seeded from the synthetic generator so the
    # service produces data with no external credentials. Real connectors register when
    # their credentials are present (Phase 3).
    seed_synthetic: bool = True
    # Run initial backfill once on start.
    run_initial_sync: bool = True
