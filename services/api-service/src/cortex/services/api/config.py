"""api-service configuration."""

from __future__ import annotations

from cortex.platform.config import ServiceSettings

SERVICE_NAME = "api-service"


class ApiSettings(ServiceSettings):
    http_port: int = 8000
