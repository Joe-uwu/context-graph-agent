"""entity-service process entrypoint.

Runs the Kafka consumer (raw.events -> entities.extracted) on a background thread and
serves the HTTP surface (health/ready/metrics + /api/v1/extract). In the in-memory
runtime the bus has no consumer loop, so the process just serves HTTP; the extraction
endpoint still works because it calls the pure extractor directly.
"""

from __future__ import annotations

from cortex.platform.http import Readiness, serve
from cortex.platform.runtime import build_bus
from cortex.services.entity.config import GROUP, SERVICE_NAME, EntitySettings
from cortex.services.entity.http import create_app
from cortex.services.entity.worker import EntityWorker


def main() -> None:
    settings = EntitySettings()
    bus = build_bus(settings, client_id=GROUP)
    worker = EntityWorker(bus)
    readiness = Readiness()
    app = create_app(worker, readiness=readiness)
    serve(app, settings, service_name=SERVICE_NAME, bus=bus, group=GROUP, readiness=readiness)


if __name__ == "__main__":
    main()
