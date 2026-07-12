"""llm-service configuration."""

from __future__ import annotations

from cortex.platform.config import ServiceSettings

SERVICE_NAME = "llm-service"
GROUP = "llm-service"


class LlmSettings(ServiceSettings):
    http_port: int = 8006

    # k-hop radius of evidence gathered before reasoning.
    evidence_hops: int = 3
