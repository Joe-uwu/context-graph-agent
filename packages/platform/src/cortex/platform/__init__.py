"""Cortex platform: infrastructure every service shares.

Provides the event bus abstraction (with in-memory and Kafka implementations),
typed settings, structured logging, id/clock helpers, and health primitives, so a
service imports one package instead of re-solving cross-cutting concerns.
"""

from cortex.platform.bus import EventBus, EventHandler, InMemoryEventBus
from cortex.platform.config import ServiceSettings
from cortex.platform.http import Readiness, create_base_app, serve, start_consumer_thread
from cortex.platform.ids import new_id, ulid_like
from cortex.platform.logging import configure_logging, get_logger
from cortex.platform.observability import METRICS, Metrics, configure_tracing

__all__ = [
    "EventBus",
    "EventHandler",
    "InMemoryEventBus",
    "ServiceSettings",
    "new_id",
    "ulid_like",
    "configure_logging",
    "get_logger",
    "METRICS",
    "Metrics",
    "configure_tracing",
    "Readiness",
    "create_base_app",
    "serve",
    "start_consumer_thread",
]
