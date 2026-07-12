"""notification-service HTTP surface.

GET /api/v1/notifications returns the routed feed (highest risk first). POST
/api/v1/actions records a user action (ack/dismiss suppresses future alerts for the
target; snooze is recorded): it applies to the engine immediately and publishes a
user.actions event so other consumers see it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cortex.contracts import Topic, new_event
from cortex.contracts.enums import UserActionType
from cortex.contracts.payloads import UserAction
from cortex.platform.bus import EventBus
from cortex.platform.http import Readiness, create_base_app
from cortex.services.notification.engine import Notification, NotificationEngine

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI

PRODUCER = "notification-service@0.1.0"


def _notif_json(n: Notification) -> dict:
    return {
        "id": n.id, "node_id": n.node_id, "channel": n.channel.value, "title": n.title,
        "body": n.body, "risk_score": n.risk_score, "confidence": n.confidence,
        "recipients": n.recipients, "fingerprint": n.fingerprint,
        "created_at": n.created_at.isoformat(), "acknowledged": n.acknowledged,
    }


def create_app(
    engine: NotificationEngine,
    *,
    bus: EventBus | None = None,
    org_id: str = "org_demo",
    readiness: Readiness | None = None,
) -> "FastAPI":
    from fastapi import Body, Header, HTTPException

    app = create_base_app("notification-service", readiness=readiness)

    @app.get("/api/v1/notifications", tags=["notification"], summary="Routed notification feed")
    def feed(x_org_id: str | None = Header(default=None)) -> dict:
        org = x_org_id or org_id
        return {"data": [_notif_json(n) for n in engine.feed], "meta": {"org_id": org}, "errors": []}

    @app.post("/api/v1/actions", tags=["notification"], summary="Record a user action")
    def action(body: dict = Body(...), x_org_id: str | None = Header(default=None)) -> dict:
        org = x_org_id or org_id
        try:
            act = UserActionType(str(body.get("action", "")))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="unknown action") from exc
        target = str(body.get("target_id", ""))
        actor = str(body.get("actor", "unknown"))
        if not target:
            raise HTTPException(status_code=422, detail="target_id required")
        if act in (UserActionType.ACK, UserActionType.DISMISS):
            engine.suppress(target)
        if bus is not None:
            bus.publish(
                Topic.USER_ACTIONS,
                new_event(
                    org_id=org, type="user.action", producer=PRODUCER,
                    payload=UserAction(action=act, target_id=target, actor=actor),
                ),
            )
        return {"data": {"action": act.value, "target_id": target}, "meta": {"org_id": org}, "errors": []}

    @app.get("/api/v1/stats", tags=["notification"], summary="Feed size")
    def stats() -> dict:
        return {"data": {"notifications": len(engine.feed)}, "meta": {}, "errors": []}

    return app
