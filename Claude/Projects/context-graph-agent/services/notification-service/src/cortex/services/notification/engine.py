"""Notification engine: fingerprint dedup, interrupt bar, channel routing.

Two gates keep this from being a spam firehose: the upstream reason threshold bounds how
often reasoning runs, and the interrupt bar here bounds how often a human is interrupted.
Below the bar, items fold into the digest instead of paging someone.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from cortex.contracts.enums import NotificationChannel
from cortex.contracts.payloads import ReasoningProduced
from cortex.platform.ids import new_id


@dataclass
class Notification:
    id: str
    node_id: str
    channel: NotificationChannel
    title: str
    body: str
    risk_score: float
    confidence: float
    fingerprint: str
    recipients: list[str]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged: bool = False


class NotificationEngine:
    def __init__(self, *, interrupt_at: float = 0.75) -> None:
        self._interrupt_at = interrupt_at
        self._by_fingerprint: dict[str, Notification] = {}
        self._suppressed: set[str] = set()  # node ids acked/dismissed
        self._covered: set[str] = set()  # node ids already inside a delivered alert's evidence
        self._feed: list[Notification] = []

    def consider(self, reasoning: ReasoningProduced) -> Notification | None:
        if reasoning.node_id in self._suppressed:
            return None
        # Bundle: if this node is already part of an existing alert's evidence cluster,
        # fold it in rather than raising a second alert about the same situation.
        if reasoning.node_id in self._covered:
            return None
        fingerprint = self._fingerprint(reasoning)
        if fingerprint in self._by_fingerprint:
            self._by_fingerprint[fingerprint].risk_score = reasoning.risk_score
            return None

        interrupt = reasoning.risk_score >= self._interrupt_at
        channel = NotificationChannel.SLACK if interrupt else NotificationChannel.DIGEST
        notif = Notification(
            id=new_id("ntf"), node_id=reasoning.node_id, channel=channel,
            title=reasoning.summary, body=reasoning.explanation,
            risk_score=reasoning.risk_score, confidence=reasoning.confidence,
            fingerprint=fingerprint, recipients=self._recipients(reasoning),
        )
        self._by_fingerprint[fingerprint] = notif
        self._feed.append(notif)
        # Mark every node in this alert's evidence as covered so the rest of the cluster
        # bundles into this one.
        self._covered.add(reasoning.node_id)
        self._covered.update(c.ref_id for c in reasoning.citations if c.kind == "node")
        return notif

    def suppress(self, node_id: str) -> None:
        self._suppressed.add(node_id)

    @property
    def feed(self) -> list[Notification]:
        return sorted(self._feed, key=lambda n: n.risk_score, reverse=True)

    @staticmethod
    def _fingerprint(reasoning: ReasoningProduced) -> str:
        basis = reasoning.node_id + "|" + ",".join(sorted(c.ref_id for c in reasoning.citations))
        return hashlib.sha256(basis.encode()).hexdigest()[:16]

    @staticmethod
    def _recipients(reasoning: ReasoningProduced) -> list[str]:
        # Routing target. The specific owner is named in the recommended action; the
        # on-call rotation is the reliable delivery target for an interrupt.
        return ["oncall"]
