"""Notification worker: consume reasoning.produced + user.actions, route notifications."""

from __future__ import annotations

from collections.abc import Callable

from cortex.contracts import Event, Topic, new_event
from cortex.contracts.enums import UserActionType
from cortex.contracts.payloads import NotificationSent, ReasoningProduced, UserAction
from cortex.platform.bus import EventBus
from cortex.platform.logging import get_logger
from cortex.platform.observability import METRICS
from cortex.services.notification.engine import Notification, NotificationEngine

log = get_logger("cortex.notification")

PRODUCER = "notification-service@0.1.0"


class NotificationWorker:
    def __init__(
        self, bus: EventBus, *, engine: NotificationEngine | None = None,
        sink: Callable[[Notification], None] | None = None,
    ) -> None:
        self._bus = bus
        self._engine = engine or NotificationEngine()
        self._sink = sink
        bus.subscribe(Topic.REASONING_PRODUCED, self.handle_reasoning, group="notification-service")
        bus.subscribe(Topic.USER_ACTIONS, self.handle_action, group="notification-service")

    @property
    def engine(self) -> NotificationEngine:
        return self._engine

    def handle_reasoning(self, event: Event) -> None:
        reasoning = ReasoningProduced.model_validate(event.payload)
        METRICS.inc("cortex_events_processed_total", service="notification-service")
        notif = self._engine.consider(reasoning)
        if notif is None:
            return
        METRICS.inc("cortex_notifications_sent_total", service="notification-service", channel=notif.channel.value)
        if self._sink:
            self._sink(notif)
        self._bus.publish(
            Topic.NOTIFICATIONS_SENT,
            new_event(
                org_id=event.org_id, type="notification.sent", producer=PRODUCER,
                trace_id=event.trace_id,
                payload=NotificationSent(
                    notification_id=notif.id, node_id=notif.node_id, channel=notif.channel,
                    recipients=notif.recipients, fingerprint=notif.fingerprint,
                    title=notif.title, body=notif.body, risk_score=notif.risk_score,
                    confidence=notif.confidence,
                ),
            ),
        )
        log.info("notification routed", extra={"extra_fields": {
            "channel": notif.channel.value, "score": notif.risk_score,
        }})

    def handle_action(self, event: Event) -> None:
        action = UserAction.model_validate(event.payload)
        if action.action in (UserActionType.ACK, UserActionType.DISMISS):
            self._engine.suppress(action.target_id)
