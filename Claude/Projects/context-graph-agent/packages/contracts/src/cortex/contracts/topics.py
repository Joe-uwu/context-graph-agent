"""Kafka topic catalog. One place names the topics so producers and consumers agree.

See docs/design/api-and-events.md for producers/consumers and the DLQ convention.
"""

from __future__ import annotations

from enum import Enum


class Topic(str, Enum):
    RAW_EVENTS = "raw.events"
    ENTITIES_EXTRACTED = "entities.extracted"
    GRAPH_CHANGES = "graph.changes"
    RISK_SCORED = "risk.scored"
    REASONING_PRODUCED = "reasoning.produced"
    NOTIFICATIONS_SENT = "notifications.sent"
    USER_ACTIONS = "user.actions"

    def dlq(self) -> str:
        """Dead-letter topic for this topic."""
        return f"{self.value}.dlq"
