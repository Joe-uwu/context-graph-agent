"""Typed graph node and edge models.

Every node/edge carries provenance (asserting event ids), confidence, and temporal
validity (valid_from/valid_to), matching docs/data/graph-model.md. Edges are closed
by setting valid_to rather than deleted, which preserves history for temporal queries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from cortex.contracts.enums import DiscoveredBy, EdgeType, NodeLabel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Node(BaseModel):
    id: str
    org_id: str
    label: NodeLabel
    natural_key: str
    source: str
    properties: dict[str, Any] = Field(default_factory=dict)
    provenance: list[str] = Field(default_factory=list)
    urgency: float = 0.0
    urgency_features: dict[str, float] = Field(default_factory=dict)
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    def display(self) -> str:
        return str(self.properties.get("title") or self.properties.get("name") or self.natural_key)


class Edge(BaseModel):
    id: str
    org_id: str
    type: EdgeType
    from_id: str
    to_id: str
    confidence: float = 1.0
    discovered_by: DiscoveredBy = DiscoveredBy.RULE
    properties: dict[str, Any] = Field(default_factory=dict)
    provenance: list[str] = Field(default_factory=list)
    valid_from: datetime = Field(default_factory=_utcnow)
    valid_to: datetime | None = None

    @property
    def is_current(self) -> bool:
        return self.valid_to is None
