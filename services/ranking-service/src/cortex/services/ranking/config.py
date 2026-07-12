"""ranking-service configuration."""

from __future__ import annotations

from cortex.platform.config import ServiceSettings

SERVICE_NAME = "ranking-service"
GROUP = "ranking-service"


class RankingSettings(ServiceSettings):
    http_port: int = 8005

    # Only nodes scoring at/above this emit risk.scored (bounds how often the LLM runs).
    reason_at: float = 0.60
    # k-hop radius scored around each changed node.
    hops: int = 2
