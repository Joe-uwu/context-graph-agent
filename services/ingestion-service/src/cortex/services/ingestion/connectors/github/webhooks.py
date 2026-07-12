"""GitHub webhook verification and parsing.

verify_signature checks the ``X-Hub-Signature-256`` HMAC-SHA256 over the raw request body
with a constant-time compare (never trust an unsigned or mismatched delivery). parse_event
turns a verified delivery into RawEvents using the same normalizers as the poll connector,
so a pull request looks identical whether it arrived by backfill or webhook.
"""

from __future__ import annotations

import hashlib
import hmac

from cortex.contracts.payloads import RawEvent
from cortex.services.ingestion.connectors.github.normalize import (
    normalize_issue,
    normalize_pull_request,
    normalize_push_commit,
    normalize_release,
)


def sign(secret: str, body: bytes) -> str:
    """Compute the ``sha256=...`` signature GitHub sends for a payload (used in tests too)."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    return hmac.compare_digest(sign(secret, body), signature_header)


def _repo_full(payload: dict) -> str:
    return str((payload.get("repository") or {}).get("full_name", "unknown"))


def parse_event(event_type: str, payload: dict) -> list[RawEvent]:
    """Turn a verified delivery into RawEvents. Unknown/ignored events yield an empty list."""
    repo = _repo_full(payload)
    action = payload.get("action")

    if event_type == "pull_request" and payload.get("pull_request"):
        return [normalize_pull_request(repo, payload["pull_request"], action=action)]
    if event_type == "issues" and payload.get("issue"):
        return [normalize_issue(repo, payload["issue"], action=action)]
    if event_type == "release" and payload.get("release"):
        return [normalize_release(repo, payload["release"], action=action)]
    if event_type == "push":
        ref = payload.get("ref")
        return [normalize_push_commit(repo, c, ref=ref) for c in payload.get("commits", [])]
    # ping, and any event we don't model, are acknowledged with no events.
    return []


SUPPORTED_EVENTS = ("pull_request", "issues", "release", "push", "ping")
