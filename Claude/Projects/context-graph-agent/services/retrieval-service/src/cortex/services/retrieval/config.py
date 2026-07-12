"""retrieval-service configuration."""

from __future__ import annotations

from cortex.platform.config import ServiceSettings

SERVICE_NAME = "retrieval-service"
GROUP = "retrieval-service"


class RetrievalSettings(ServiceSettings):
    http_port: int = 8004

    # Default k-hop radius for evidence gathering.
    evidence_hops: int = 2
