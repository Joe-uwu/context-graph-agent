"""ingestion-service process entrypoint.

Registers whichever connectors have credentials configured; each defaults to its mock
twin (seeded from the synthetic generator) otherwise so the service is never dead. Runs
the incremental-sync consumer on a background thread and serves the HTTP surface. In a
real deployment a scheduler (Celery beat) drives periodic incremental syncs; here the
initial backfill runs once on start and /api/v1/sync triggers it on demand.
"""

from __future__ import annotations

from cortex.platform.http import Readiness, serve
from cortex.platform.logging import get_logger
from cortex.platform.runtime import build_bus
from cortex.services.ingestion.config import GROUP, SERVICE_NAME, IngestionSettings
from cortex.services.ingestion.connectors.github import GitHubSettings, build_github_connector
from cortex.services.ingestion.http import create_app
from cortex.services.ingestion.worker import IngestionWorker

log = get_logger("cortex.ingestion")


def main() -> None:
    settings = IngestionSettings()
    github_settings = GitHubSettings()
    bus = build_bus(settings, client_id=GROUP)
    worker = IngestionWorker(bus, settings.org_id)

    # Register the real GitHub connector when credentials are configured (Phase 3).
    github = build_github_connector(github_settings)
    if github is not None:
        worker.register(github)
        log.info("registered github connector")

    # Fall back to the synthetic mock twin so the service is never dead without creds.
    if settings.seed_synthetic and github is None:
        from cortex.services.ingestion.connectors.mock import MockConnector
        from cortex.tools.synthetic.scenario import deploy_will_fail_scenario

        worker.register(MockConnector("mixed", deploy_will_fail_scenario()))

    readiness = Readiness()
    app = create_app(worker, webhook_secret=github_settings.webhook_secret, readiness=readiness)

    def _on_ready() -> None:
        if settings.run_initial_sync:
            worker.run_initial_sync()

    serve(
        app, settings, service_name=SERVICE_NAME, bus=bus, group=GROUP,
        readiness=readiness, on_ready=_on_ready,
    )


if __name__ == "__main__":
    main()
