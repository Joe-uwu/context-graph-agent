"""notification-service configuration."""

from __future__ import annotations

from cortex.platform.config import ServiceSettings

SERVICE_NAME = "notification-service"
GROUP = "notification-service"


class NotificationSettings(ServiceSettings):
    http_port: int = 8007

    # Risk at/above which an item interrupts a human (Slack) rather than folding into the
    # digest.
    interrupt_at: float = 0.75
