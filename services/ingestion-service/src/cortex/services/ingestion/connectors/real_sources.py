"""Real connectors for the remaining sources.

Each follows the same shape as GitHubConnector: subclass BaseConnector, implement the
three sync methods against the source API, normalize to RawEvent. Kept compact — the
sync bodies are the only work left to make them live, and the mock twin covers demo/test
in the meantime. Separated per source so they can grow independently.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from cortex.contracts.enums import Source
from cortex.contracts.payloads import RawEvent
from cortex.services.ingestion.base import BaseConnector


class _RealConnector(BaseConnector):
    _source: Source

    def __init__(self, **credentials: str) -> None:
        super().__init__(self._source.value)
        self._credentials = credentials

    def initial_sync(self) -> Sequence[RawEvent]:  # pragma: no cover - needs credentials
        raise NotImplementedError(f"{self._source.value} initial_sync needs API wiring")

    def incremental_sync(self, since: str | None) -> Sequence[RawEvent]:  # pragma: no cover
        raise NotImplementedError(f"{self._source.value} incremental_sync needs API wiring")

    def stream(self) -> Iterator[RawEvent]:  # pragma: no cover
        raise NotImplementedError(f"{self._source.value} stream needs API wiring")


class SlackConnector(_RealConnector):
    # OAuth (bot token) → conversations.history / search; RTM or Events API for stream.
    _source = Source.SLACK


class JiraConnector(_RealConnector):
    # OAuth/API token → /rest/api/3/search with JQL; webhooks for stream.
    _source = Source.JIRA


class NotionConnector(_RealConnector):
    # Integration token → /v1/search + block children; no push, so incremental polling.
    _source = Source.NOTION


class CalendarConnector(_RealConnector):
    # Google OAuth → events.list with syncToken; push notifications channel for stream.
    _source = Source.CALENDAR


class PagerDutyConnector(_RealConnector):
    # API token → /incidents, /log_entries; webhooks (v3) for stream.
    _source = Source.PAGERDUTY
