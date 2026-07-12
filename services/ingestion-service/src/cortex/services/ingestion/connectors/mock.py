"""Mock connector: replays pre-generated events for any source.

The synthetic generator (tools/synthetic) produces cross-source-consistent RawEvents;
this connector replays them behind the same interface as the real connectors, so the
whole pipeline runs with no credentials (ADR-0003).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from cortex.contracts.payloads import RawEvent
from cortex.services.ingestion.base import BaseConnector


class MockConnector(BaseConnector):
    def __init__(self, source: str, events: Sequence[RawEvent]) -> None:
        super().__init__(source)
        self._events = list(events)

    def initial_sync(self) -> Sequence[RawEvent]:
        return [e for e in self._events if self.dedup(e.external_id)]

    def incremental_sync(self, since: str | None) -> Sequence[RawEvent]:
        out = []
        for e in self._events:
            if since and e.occurred_at.isoformat() <= since:
                continue
            if self.dedup(e.external_id):
                out.append(e)
        return out

    def stream(self) -> Iterator[RawEvent]:
        yield from (e for e in self._events if self.dedup(e.external_id))
