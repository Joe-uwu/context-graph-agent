"""Topic-specific payload schemas carried inside the Event envelope.

Each payload is versioned with the envelope's schema_version. Changes must be additive
within a major version; the CI compatibility check enforces this.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from cortex.contracts.enums import (
    ChangeKind,
    DiscoveredBy,
    EdgeType,
    NodeLabel,
    NotificationChannel,
    Source,
    UserActionType,
)

# --- raw.events -------------------------------------------------------------------


class RawEvent(BaseModel):
    """A normalized source event. `kind` is the source-native event name."""

    source: Source
    kind: str
    external_id: str
    occurred_at: datetime
    actor: str | None = None
    title: str | None = None
    body: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


# --- entities.extracted -----------------------------------------------------------


class ExtractedNode(BaseModel):
    label: NodeLabel
    natural_key: str
    source: Source
    properties: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0


class ExtractedEdge(BaseModel):
    type: EdgeType
    from_key: str
    to_key: str
    confidence: float = 1.0
    discovered_by: DiscoveredBy = DiscoveredBy.RULE
    properties: dict[str, Any] = Field(default_factory=dict)


class EntitiesExtracted(BaseModel):
    source_event_id: str
    nodes: list[ExtractedNode] = Field(default_factory=list)
    edges: list[ExtractedEdge] = Field(default_factory=list)


# --- graph.changes ----------------------------------------------------------------


class GraphChanged(BaseModel):
    changed_node_ids: list[str]
    change_kind: ChangeKind


# --- risk.scored ------------------------------------------------------------------


class RiskScored(BaseModel):
    node_id: str
    score: float
    confidence: float
    features: dict[str, float] = Field(default_factory=dict)


# --- reasoning.produced -----------------------------------------------------------


class Citation(BaseModel):
    """A pointer to graph evidence backing a claim."""

    ref_id: str  # node id or edge id
    kind: str  # "node" | "edge"
    label: str
    confidence: float


class RecommendedAction(BaseModel):
    title: str
    detail: str


class ReasoningProduced(BaseModel):
    node_id: str
    summary: str
    explanation: str
    actions: list[RecommendedAction] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float
    risk_score: float


# --- notifications.sent -----------------------------------------------------------


class NotificationSent(BaseModel):
    notification_id: str
    node_id: str
    channel: NotificationChannel
    recipients: list[str]
    fingerprint: str
    title: str
    body: str
    risk_score: float
    confidence: float


# --- user.actions -----------------------------------------------------------------


class UserAction(BaseModel):
    action: UserActionType
    target_id: str
    actor: str
    snooze_until: datetime | None = None
