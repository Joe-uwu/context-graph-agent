"""graph-service configuration."""

from __future__ import annotations

from cortex.platform.config import ServiceSettings

SERVICE_NAME = "graph-service"
GROUP = "graph-service"


class GraphSettings(ServiceSettings):
    http_port: int = 8003
