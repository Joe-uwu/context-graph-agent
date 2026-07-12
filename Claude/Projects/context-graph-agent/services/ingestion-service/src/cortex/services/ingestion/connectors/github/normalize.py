"""Normalize GitHub REST/webhook objects into the platform's RawEvent.

Both the polling connector and the webhook handler produce the same RawEvents from the
same objects, so the normalization lives here once. external_id is stable per object so
downstream dedup and idempotent graph writes work whether an object arrives by backfill,
incremental poll, or webhook.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cortex.contracts.enums import Source
from cortex.contracts.payloads import RawEvent


def parse_ts(value: Any) -> datetime:
    """Parse a GitHub ISO-8601 timestamp (``...Z``) to an aware UTC datetime."""
    if not value:
        return datetime.now(timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _first_line(text: str | None) -> str | None:
    if not text:
        return None
    return text.splitlines()[0].strip() or None


def normalize_pull_request(repo_full: str, pr: dict, *, action: str | None = None) -> RawEvent:
    number = pr.get("number")
    labels = [label.get("name") for label in pr.get("labels", []) if label.get("name")]
    return RawEvent(
        source=Source.GITHUB,
        kind="pull_request",
        external_id=f"github:{repo_full}#pr-{number}",
        occurred_at=parse_ts(pr.get("updated_at") or pr.get("created_at")),
        actor=(pr.get("user") or {}).get("login"),
        title=pr.get("title"),
        body=pr.get("body"),
        attributes={
            "repo": repo_full,
            "number": number,
            "state": pr.get("state"),
            "merged": pr.get("merged"),
            "draft": pr.get("draft"),
            "html_url": pr.get("html_url"),
            "head": (pr.get("head") or {}).get("ref"),
            "base": (pr.get("base") or {}).get("ref"),
            "labels": labels,
            "action": action,
        },
    )


def normalize_issue(repo_full: str, issue: dict, *, action: str | None = None) -> RawEvent:
    number = issue.get("number")
    labels = [label.get("name") for label in issue.get("labels", []) if label.get("name")]
    return RawEvent(
        source=Source.GITHUB,
        kind="issue",
        external_id=f"github:{repo_full}#issue-{number}",
        occurred_at=parse_ts(issue.get("updated_at") or issue.get("created_at")),
        actor=(issue.get("user") or {}).get("login"),
        title=issue.get("title"),
        body=issue.get("body"),
        attributes={
            "repo": repo_full,
            "number": number,
            "state": issue.get("state"),
            "html_url": issue.get("html_url"),
            "labels": labels,
            "comments": issue.get("comments"),
            "action": action,
        },
    )


def normalize_commit(repo_full: str, commit: dict) -> RawEvent:
    """Normalize a commit from the REST list-commits endpoint."""
    sha = str(commit.get("sha", ""))
    inner = commit.get("commit", {})
    author = inner.get("author", {})
    message = inner.get("message")
    return RawEvent(
        source=Source.GITHUB,
        kind="commit",
        external_id=f"github:{repo_full}@{sha[:12]}",
        occurred_at=parse_ts(author.get("date")),
        actor=(commit.get("author") or {}).get("login") or author.get("name"),
        title=_first_line(message),
        body=message,
        attributes={
            "repo": repo_full,
            "sha": sha,
            "html_url": commit.get("html_url"),
        },
    )


def normalize_push_commit(repo_full: str, commit: dict, *, ref: str | None = None) -> RawEvent:
    """Normalize a commit from a push webhook payload (different shape than the REST list)."""
    sha = str(commit.get("id", ""))
    message = commit.get("message")
    author = commit.get("author", {})
    return RawEvent(
        source=Source.GITHUB,
        kind="commit",
        external_id=f"github:{repo_full}@{sha[:12]}",
        occurred_at=parse_ts(commit.get("timestamp")),
        actor=author.get("username") or author.get("name"),
        title=_first_line(message),
        body=message,
        attributes={
            "repo": repo_full,
            "sha": sha,
            "ref": ref,
            "html_url": commit.get("url"),
        },
    )


def normalize_release(repo_full: str, release: dict, *, action: str | None = None) -> RawEvent:
    return RawEvent(
        source=Source.GITHUB,
        kind="release",
        external_id=f"github:{repo_full}#release-{release.get('id')}",
        occurred_at=parse_ts(release.get("published_at") or release.get("created_at")),
        actor=(release.get("author") or {}).get("login"),
        title=release.get("name") or release.get("tag_name"),
        body=release.get("body"),
        attributes={
            "repo": repo_full,
            "tag": release.get("tag_name"),
            "prerelease": release.get("prerelease"),
            "draft": release.get("draft"),
            "html_url": release.get("html_url"),
            "action": action,
        },
    )
