"""Cortex shared contracts: the wire format every service agrees on.

The event envelope, payload schemas, enums, and the topic catalog live here and
nowhere else, so producers and consumers cannot drift. See docs/design/api-and-events.md.
"""

from cortex.contracts.enums import (
    ChangeKind,
    EdgeType,
    NodeLabel,
    NotificationChannel,
    Source,
    UserActionType,
)
from cortex.contracts.envelope import Event, new_event
from cortex.contracts.payloads import (
    EntitiesExtracted,
    ExtractedEdge,
    ExtractedNode,
    GraphChanged,
    NotificationSent,
    RawEvent,
    ReasoningProduced,
    RiskScored,
    UserAction,
)
from cortex.contracts.topics import Topic

__all__ = [
    "ChangeKind",
    "EdgeType",
    "NodeLabel",
    "NotificationChannel",
    "Source",
    "UserActionType",
    "Event",
    "new_event",
    "EntitiesExtracted",
    "ExtractedEdge",
    "ExtractedNode",
    "GraphChanged",
    "NotificationSent",
    "RawEvent",
    "ReasoningProduced",
    "RiskScored",
    "UserAction",
    "Topic",
]
