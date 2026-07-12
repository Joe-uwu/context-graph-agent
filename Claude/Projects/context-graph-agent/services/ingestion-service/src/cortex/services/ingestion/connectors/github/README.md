# GitHub connector

The first real source connector. It demonstrates the full pattern the other five follow:
OAuth, webhooks, pagination, incremental sync, rate limiting, retry, and Kafka publishing.

## Modules

| File | Responsibility |
| --- | --- |
| `auth.py` | `TokenProvider` strategies: `StaticToken` (PAT/installation token), `OAuthApp` + `RefreshingOAuthToken` (authorization-code web flow with refresh), `GitHubApp` (RS256 app JWT → installation access token, cached) |
| `client.py` | `GitHubClient`: Link-header pagination, `Retry-After`/`X-RateLimit-Reset` handling (primary + secondary limits), retry with exponential backoff + full jitter |
| `connector.py` | `GitHubConnector`: `initial_sync` (repos → PRs/issues/commits/releases), `incremental_sync` (since cursor), dedup |
| `normalize.py` | GitHub objects → `RawEvent` (shared by polling and webhooks so IDs match) |
| `webhooks.py` | `verify_signature` (HMAC-SHA256, constant-time), `parse_event` → `RawEvent`s |
| `config.py` | `GitHubSettings` + `build_github_connector` (picks the strongest configured auth) |

## Auth

Configured via `CORTEX_GITHUB_*`. The factory picks the strongest strategy present:

1. **GitHub App** — `CORTEX_GITHUB_APP_ID`, `CORTEX_GITHUB_PRIVATE_KEY` (or `_PRIVATE_KEY_PATH`), `CORTEX_GITHUB_INSTALLATION_ID`. Needs the `github` extra (`pip install ".[github]"`) for PyJWT.
2. **OAuth refresh** — `CORTEX_GITHUB_CLIENT_ID`, `CORTEX_GITHUB_CLIENT_SECRET`, `CORTEX_GITHUB_OAUTH_REFRESH_TOKEN`.
3. **Static token / PAT** — `CORTEX_GITHUB_TOKEN`.

Plus `CORTEX_GITHUB_ORG` (required) and optional `CORTEX_GITHUB_REPOS` (comma-separated;
empty = every org repo). With none of the above set, ingestion falls back to the synthetic
mock twin so the service still runs.

The OAuth web flow: `OAuthApp.authorize_url(state=...)` → redirect the user → GitHub calls
back with a `code` → `exchange_code(code)` → `OAuthTokens`. `RefreshingOAuthToken` refreshes
transparently before expiry.

## Sync

`initial_sync()` backfills every accessible repo's pull requests, issues, commits, and
releases, following the `Link` header across pages. `incremental_sync(since)` passes the
cursor to `?since=` where the API supports it and stops early on update-sorted lists.
Events are deduped per process by stable `external_id`, then published to `raw.events`.

## Webhooks

Point a GitHub webhook (content type `application/json`, secret =
`CORTEX_GITHUB_WEBHOOK_SECRET`) at `POST /webhooks/github` on ingestion-service. The handler
verifies `X-Hub-Signature-256`, parses `pull_request` / `issues` / `push` / `release`
deliveries into `RawEvent`s, and publishes them — the same normalized shape as the poll
path. Unsigned or mismatched deliveries return 401.

## Rate limiting & retry

`GitHubClient` records `X-RateLimit-Remaining`, waits until `X-RateLimit-Reset` on a 403/429
rate-limit response, honors `Retry-After`, and otherwise retries 5xx with exponential
backoff + jitter up to `max_retries`. `BaseConnector` adds a local token bucket over that.

## Metrics

`cortex_github_requests_total{status}`, `cortex_github_retries_total`,
`cortex_github_rate_limit_remaining`, `cortex_github_webhook_events_total{event}`,
`cortex_github_webhook_rejected_total`.
