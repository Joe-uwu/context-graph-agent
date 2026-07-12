"""Connector interface shared by every source (real and mock)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Protocol, runtime_checkable

from cortex.contracts.payloads import RawEvent


@runtime_checkable
class Connector(Protocol):
    """One source integration. `since` cursors make incremental sync resumable."""

    source: str

    def initial_sync(self) -> Sequence[RawEvent]:
        """Full backfill on first connect."""

    def incremental_sync(self, since: str | None) -> Sequence[RawEvent]:
        """Fetch events after the cursor; returns them normalized."""

    def stream(self) -> Iterator[RawEvent]:
        """Push/streaming events (webhook or socket), if the source supports it."""
