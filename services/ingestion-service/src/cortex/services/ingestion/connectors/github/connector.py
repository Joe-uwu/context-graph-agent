"""GitHub connector: backfill and incremental sync over the REST client.

initial_sync backfills every accessible repo's pull requests, issues, commits, and
releases; incremental_sync fetches only objects updated after the cursor (an ISO-8601
timestamp). Push-style delivery is handled by the webhook endpoint, not a poll loop, so
stream() is empty here. Dedup (BaseConnector) drops objects already seen in this process.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from cortex.contracts.enums import Source
from cortex.contracts.payloads import RawEvent
from cortex.platform.logging import get_logger
from cortex.services.ingestion.base import BaseConnector
from cortex.services.ingestion.connectors.github.auth import StaticToken, TokenProvider
from cortex.services.ingestion.connectors.github.client import GitHubClient
from cortex.services.ingestion.connectors.github.normalize import (
    normalize_commit,
    normalize_issue,
    normalize_pull_request,
    normalize_release,
)

log = get_logger("cortex.ingestion.github")


class GitHubConnector(BaseConnector):
    def __init__(
        self,
        auth: TokenProvider | str,
        org: str,
        *,
        client: GitHubClient | None = None,
        repos: Sequence[str] | None = None,
        page_limit: int | None = None,
    ) -> None:
        super().__init__(Source.GITHUB.value, rate_per_sec=15.0, capacity=30)
        provider: TokenProvider = StaticToken(auth) if isinstance(auth, str) else auth
        self._client = client or GitHubClient(provider)
        self._org = org
        self._repos = list(repos) if repos else None
        self._page_limit = page_limit

    def initial_sync(self) -> Sequence[RawEvent]:
        return self._collect(since=None)

    def incremental_sync(self, since: str | None) -> Sequence[RawEvent]:
        return self._collect(since=since)

    def stream(self) -> Iterator[RawEvent]:
        # Real-time delivery arrives via the webhook endpoint (see webhooks.py); the poll
        # connector has no long-lived stream.
        return iter(())

    # --- internals ---------------------------------------------------------------

    def _collect(self, *, since: str | None) -> list[RawEvent]:
        events: list[RawEvent] = []
        for repo_full in self._repo_names():
            events.extend(self._repo_events(repo_full, since=since))
        deduped = [e for e in events if self.dedup(e.external_id)]
        log.info(
            "github sync",
            extra={"extra_fields": {
                "org": self._org, "since": since, "events": len(deduped),
            }},
        )
        return deduped

    def _repo_names(self) -> list[str]:
        if self._repos:
            return [r if "/" in r else f"{self._org}/{r}" for r in self._repos]
        return [
            repo["full_name"]
            for repo in self._client.paginate(
                f"/orgs/{self._org}/repos", params={"type": "all", "sort": "updated"},
                limit=self._page_limit,
            )
        ]

    def _repo_events(self, repo_full: str, *, since: str | None) -> list[RawEvent]:
        out: list[RawEvent] = []

        for pr in self._client.paginate(
            f"/repos/{repo_full}/pulls",
            params={"state": "all", "sort": "updated", "direction": "desc"},
            limit=self._page_limit,
        ):
            if _stale(pr.get("updated_at"), since):
                break  # sorted desc by update time: everything after is older
            out.append(normalize_pull_request(repo_full, pr))

        issue_params = {"state": "all", "sort": "updated", "direction": "desc"}
        if since:
            issue_params["since"] = since
        for issue in self._client.paginate(
            f"/repos/{repo_full}/issues", params=issue_params, limit=self._page_limit
        ):
            if "pull_request" in issue:
                continue  # the issues endpoint also returns PRs; skip those here
            if _stale(issue.get("updated_at"), since):
                continue  # defensive: filter client-side too, not just via ?since=
            out.append(normalize_issue(repo_full, issue))

        commit_params = {"since": since} if since else {}
        for commit in self._client.paginate(
            f"/repos/{repo_full}/commits", params=commit_params, limit=self._page_limit
        ):
            commit_date = (commit.get("commit", {}).get("author", {}) or {}).get("date")
            if _stale(commit_date, since):
                continue
            out.append(normalize_commit(repo_full, commit))

        for release in self._client.paginate(
            f"/repos/{repo_full}/releases", limit=self._page_limit
        ):
            if _stale(release.get("published_at") or release.get("created_at"), since):
                continue
            out.append(normalize_release(repo_full, release))

        return out


def _stale(updated_at: str | None, since: str | None) -> bool:
    """True when an object's timestamp is at or before the cursor (already ingested)."""
    if not since or not updated_at:
        return False
    return str(updated_at) <= since
