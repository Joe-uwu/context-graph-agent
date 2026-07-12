"""entity-service configuration."""

from __future__ import annotations

from cortex.platform.config import ServiceSettings

SERVICE_NAME = "entity-service"
GROUP = "entity-service"


class EntitySettings(ServiceSettings):
    """entity-service is a stateless transform; it inherits the shared settings and adds
    no store credentials of its own."""

    http_port: int = 8002
