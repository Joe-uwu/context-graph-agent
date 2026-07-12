"""GitHub REST client: pagination, rate-limit handling, and retry.

- Pagination follows the RFC 5988 ``Link`` header (``rel="next"``) rather than guessing
  page counts, so it works for every list endpoint.
- Rate limiting honors ``Retry-After`` and the ``X-RateLimit-Reset`` epoch when GitHub
  returns 403/429 (primary and secondary limits), sleeping until the window reopens.
- Retry covers 5xx and rate-limit responses with exponential backoff plus jitter, capped by
  ``max_retries``; non-retryable 4xx errors raise immediately.

The HTTP transport is injectable (``http=``), so tests drive it with httpx.MockTransport
and a no-op sleeper — no network required.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterator

import httpx

from cortex.platform.logging import get_logger
from cortex.platform.observability import METRICS
from cortex.services.ingestion.connectors.github.auth import GITHUB_API, TokenProvider

log = get_logger("cortex.ingestion.github")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class GitHubClient:
    def __init__(
        self,
        auth: TokenProvider,
        *,
        base_url: str = GITHUB_API,
        http: httpx.Client | None = None,
        max_retries: int = 5,
        base_delay: float = 0.5,
        max_delay: float = 60.0,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        api_version: str = "2022-11-28",
    ) -> None:
        self._auth = auth
        self._base = base_url.rstrip("/")
        self._http = http or httpx.Client(timeout=30.0)
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._sleep = sleeper
        self._clock = clock
        self._api_version = api_version

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._auth.token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self._api_version,
        }

    def get(self, path: str, *, params: dict | None = None) -> httpx.Response:
        return self._request("GET", self._url(path), params=params)

    def get_json(self, path: str, *, params: dict | None = None):
        return self.get(path, params=params).json()

    def paginate(
        self, path: str, *, params: dict | None = None, per_page: int = 100, limit: int | None = None
    ) -> Iterator[dict]:
        """Yield items across every page, following the Link header.

        Handles both list responses and search-style ``{"items": [...]}`` responses.
        """
        query = dict(params or {})
        query.setdefault("per_page", per_page)
        url: str | None = self._url(path)
        first = True
        count = 0
        while url:
            resp = self._request("GET", url, params=query if first else None)
            first = False
            payload = resp.json()
            items = payload if isinstance(payload, list) else payload.get("items", [])
            for item in items:
                yield item
                count += 1
                if limit is not None and count >= limit:
                    return
            url = _next_link(resp.headers.get("Link", ""))

    def _url(self, path: str) -> str:
        return path if path.startswith("http") else f"{self._base}{path}"

    def _request(self, method: str, url: str, *, params: dict | None = None) -> httpx.Response:
        last: httpx.Response | None = None
        for attempt in range(1, self._max_retries + 1):
            resp = self._http.request(method, url, params=params, headers=self._headers())
            METRICS.inc(
                "cortex_github_requests_total",
                service="ingestion-service", status=str(resp.status_code),
            )
            self._record_rate_limit(resp)
            if resp.status_code < 400:
                return resp
            if self._should_retry(resp) and attempt < self._max_retries:
                delay = self._retry_delay(resp, attempt)
                METRICS.inc("cortex_github_retries_total", service="ingestion-service")
                log.warning(
                    "github request retry",
                    extra={"extra_fields": {
                        "status": resp.status_code, "attempt": attempt,
                        "delay_s": round(delay, 3), "url": url,
                    }},
                )
                self._sleep(delay)
                last = resp
                continue
            resp.raise_for_status()
        assert last is not None  # loop only exits early via return/raise
        last.raise_for_status()
        return last  # pragma: no cover - unreachable

    def _should_retry(self, resp: httpx.Response) -> bool:
        if resp.status_code in RETRYABLE_STATUS:
            return True
        # Primary/secondary rate limit surfaces as 403 with remaining==0 or a Retry-After.
        if resp.status_code == 403:
            if resp.headers.get("Retry-After") is not None:
                return True
            if resp.headers.get("X-RateLimit-Remaining") == "0":
                return True
        return False

    def _retry_delay(self, resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return min(float(retry_after), self._max_delay)
            except ValueError:
                pass
        if resp.headers.get("X-RateLimit-Remaining") == "0":
            reset = resp.headers.get("X-RateLimit-Reset")
            if reset is not None:
                try:
                    wait = float(reset) - self._clock()
                    if wait > 0:
                        return min(wait, self._max_delay)
                except ValueError:
                    pass
        # Exponential backoff with full jitter.
        ceiling = min(self._base_delay * (2 ** (attempt - 1)), self._max_delay)
        return random.uniform(0, ceiling)

    @staticmethod
    def _record_rate_limit(resp: httpx.Response) -> None:
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining is not None:
            try:
                METRICS.gauge(
                    "cortex_github_rate_limit_remaining", float(remaining),
                    service="ingestion-service",
                )
            except ValueError:
                pass


def _next_link(link_header: str) -> str | None:
    """Extract the ``rel="next"`` URL from a Link header, if present."""
    if not link_header:
        return None
    for part in link_header.split(","):
        segments = part.split(";")
        if len(segments) < 2:
            continue
        url = segments[0].strip().strip("<>")
        for meta in segments[1:]:
            meta = meta.strip()
            if meta in ('rel="next"', "rel=next"):
                return url
    return None
