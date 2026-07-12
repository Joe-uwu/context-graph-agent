"""notification-service process entrypoint.

Consumes reasoning.produced (routes notifications) and user.actions (suppresses acked/
dismissed targets) on a background consumer thread; serves the feed and action HTTP
surface over the same engine.
"""

from __future__ import annotations

from cortex.platform.http import Readiness, serve
from cortex.platform.logging import get_logger
from cortex.platform.runtime import build_bus
from cortex.services.notification.config import GROUP, SERVICE_NAME, NotificationSettings
from cortex.services.notification.engine import NotificationEngine
from cortex.services.notification.http import create_app
from cortex.services.notification.worker import NotificationWorker

log = get_logger("cortex.notification")


def main() -> None:
    settings = NotificationSettings()
    bus = build_bus(settings, client_id=GROUP)
    engine = NotificationEngine(interrupt_at=settings.interrupt_at)
    NotificationWorker(
        bus, engine=engine,
        sink=lambda n: log.info(
            "deliver", extra={"extra_fields": {"channel": n.channel.value, "title": n.title}}
        ),
    )
    readiness = Readiness()
    app = create_app(engine, bus=bus, readiness=readiness)
    serve(app, settings, service_name=SERVICE_NAME, bus=bus, group=GROUP, readiness=readiness)


if __name__ == "__main__":
    main()
