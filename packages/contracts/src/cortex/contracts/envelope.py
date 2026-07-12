"""The single event envelope shared by every Kafka topic.

Payload is topic-specific and validated by the consumer against its expected model.
See docs/design/api-and-events.md for the envelope contract.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


class Event(BaseModel):
    """Uniform envelope. `event_id` is the idempotency key used everywhere downstream;
    `org_id` is the Kafka partition key and tenant scope; `trace_id` stitches one trace
    from source event to delivered notification."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=lambda: _new_id("evt"))
    org_id: str
    type: str
    occurred_at: datetime = Field(default_factory=_utcnow)
    produced_at: datetime = Field(default_factory=_utcnow)
    producer: str = "unknown"
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    schema_version: int = 1
    payload: dict[str, Any] = Field(default_factory=dict)


def new_event(
    *,
    org_id: str,
    type: str,
    payload: BaseModel | dict[str, Any],
    producer: str = "unknown",
    trace_id: str | None = None,
    occurred_at: datetime | None = None,
) -> Event:
    """Build an envelope around a payload model, carrying the trace id forward."""
    body = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    kwargs: dict[str, Any] = {
        "org_id": org_id,
        "type": type,
        "payload": body,
        "producer": producer,
    }
    if trace_id is not None:
        kwargs["trace_id"] = trace_id
    if occurred_at is not None:
        kwargs["occurred_at"] = occurred_at
    return Event(**kwargs)
