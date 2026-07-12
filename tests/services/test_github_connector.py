"""GitHub connector tests: auth, client (pagination/retry/rate-limit), sync, webhooks.

Every HTTP interaction runs through an injected httpx.MockTransport and a no-op sleeper, so
the suite exercises the real code paths with no network and no wall-clock delay.
"""

from __future__ import annotations

import json

import httpx
import pytest

from cortex.contracts.enums import Source
from cortex.services.ingestion.connectors.github.auth import (
    GitHubApp,
    OAuthApp,
    OAuthTokens,
    RefreshingOAuthToken,
    StaticToken,
)
from cortex.services.ingestion.connectors.github.client import GitHubClient, _next_link
from cortex.services.ingestion.connectors.github.config import GitHubSettings, build_github_connector
from cortex.services.ingestion.connectors.github.connector import GitHubConnector
from cortex.services.ingestion.connectors.github.webhooks import (
    parse_event,
    sign,
    verify_signature,
)


def client_over(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- Link-header pagination ------------------------------------------------------


def test_next_link_parsing():
    header = '<https://api.github.com/x?page=2>; rel="next", <https://api.github.com/x?page=9>; rel="last"'
    assert _next_link(header) == "https://api.github.com/x?page=2"
    assert _next_link("") is None
    assert _next_link('<https://api.github.com/x?page=9>; rel="last"') is None


def test_paginate_follows_link_header():
    pages = {
        "1": (
            [{"id": 1}, {"id": 2}],
            {"Link": '<https://api.github.com/things?page=2>; rel="next"'},
        ),
        "2": ([{"id": 3}], {}),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page = dict(request.url.params).get("page", "1")
        body, headers = pages[page]
        return httpx.Response(200, json=body, headers=headers)

    gh = GitHubClient(StaticToken("t"), http=client_over(handler))
    items = list(gh.paginate("/things"))
    assert [i["id"] for i in items] == [1, 2, 3]


# --- retry + rate limiting -------------------------------------------------------


def test_retry_on_500_then_success():
    calls = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500, json={"message": "boom"})
        return httpx.Response(200, json={"ok": True})

    gh = GitHubClient(StaticToken("t"), http=client_over(handler), sleeper=slept.append, base_delay=0.01)
    resp = gh.get("/x")
    assert resp.json() == {"ok": True}
    assert calls["n"] == 3
    assert len(slept) == 2  # two retries slept


def test_rate_limit_403_waits_until_reset():
    calls = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                403, json={"message": "rate limited"},
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1000"},
            )
        return httpx.Response(200, json={"ok": True})

    gh = GitHubClient(
        StaticToken("t"), http=client_over(handler), sleeper=slept.append, clock=lambda: 970.0
    )
    assert gh.get("/x").json() == {"ok": True}
    # Waited reset(1000) - now(970) = 30s.
    assert slept == [30.0]


def test_retry_after_header_honored():
    calls = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={}, headers={"Retry-After": "7"})
        return httpx.Response(200, json={})

    gh = GitHubClient(StaticToken("t"), http=client_over(handler), sleeper=slept.append)
    gh.get("/x")
    assert slept == [7.0]


def test_non_retryable_4xx_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "not found"})

    gh = GitHubClient(StaticToken("t"), http=client_over(handler))
    with pytest.raises(httpx.HTTPStatusError):
        gh.get("/missing")


# --- OAuth web flow --------------------------------------------------------------


def test_oauth_authorize_url():
    app = OAuthApp("cid", "secret", redirect_uri="https://app/cb", http=client_over(lambda r: httpx.Response(200)))
    url = app.authorize_url(state="xyz", scopes=("repo", "read:org"))
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=cid" in url and "state=xyz" in url and "repo+read%3Aorg" in url


def test_oauth_exchange_and_refresh():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/login/oauth/access_token"
        body = dict(httpx.QueryParams(request.content.decode()))
        if body["grant_type"] == "authorization_code":
            assert body["code"] == "the-code"
            return httpx.Response(200, json={
                "access_token": "at1", "refresh_token": "rt1",
                "expires_in": 3600, "token_type": "bearer", "scope": "repo",
            })
        assert body["grant_type"] == "refresh_token" and body["refresh_token"] == "rt1"
        return httpx.Response(200, json={"access_token": "at2", "refresh_token": "rt2", "expires_in": 3600})

    app = OAuthApp("cid", "secret", http=client_over(handler))
    tokens = app.exchange_code("the-code")
    assert tokens.access_token == "at1" and tokens.refresh_token == "rt1"
    assert tokens.expires_at is not None

    provider = RefreshingOAuthToken(app, OAuthTokens(access_token="", refresh_token="rt1", expires_at=0.0))
    assert provider.token() == "at2"  # expired -> auto refresh
    assert provider.tokens.refresh_token == "rt2"


def test_oauth_error_response_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "bad_verification_code", "error_description": "expired"})

    app = OAuthApp("cid", "secret", http=client_over(handler))
    with pytest.raises(Exception) as exc:
        app.exchange_code("nope")
    assert "expired" in str(exc.value)


# --- GitHub App installation tokens ---------------------------------------------


def _rsa_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def test_github_app_mints_and_caches_installation_token():
    pytest.importorskip("jwt")
    pem = _rsa_pem()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.url.path == "/app/installations/42/access_tokens"
        assert request.headers["Authorization"].startswith("Bearer ")
        return httpx.Response(201, json={"token": "ghs_abc", "expires_at": "2999-01-01T00:00:00Z"})

    app = GitHubApp(123, pem, 42, http=client_over(handler), clock=lambda: 1000.0)
    jwt_token = app.app_jwt()
    assert jwt_token.count(".") == 2  # header.payload.signature
    assert app.installation_token() == "ghs_abc"
    assert app.installation_token() == "ghs_abc"  # cached
    assert calls["n"] == 1


# --- connector sync --------------------------------------------------------------


def _sync_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/orgs/acme/repos":
        return httpx.Response(200, json=[{"full_name": "acme/web"}])
    if path == "/repos/acme/web/pulls":
        return httpx.Response(200, json=[{
            "number": 7, "title": "Fix billing", "user": {"login": "joe"},
            "updated_at": "2026-01-02T00:00:00Z", "state": "open",
            "labels": [{"name": "bug"}], "head": {"ref": "fix"}, "base": {"ref": "main"},
        }])
    if path == "/repos/acme/web/issues":
        return httpx.Response(200, json=[
            {"number": 3, "title": "Bug", "user": {"login": "sam"}, "updated_at": "2026-01-02T00:00:00Z", "state": "open", "labels": []},
            {"number": 7, "pull_request": {"url": "x"}, "title": "PR-as-issue"},  # skipped
        ])
    if path == "/repos/acme/web/commits":
        return httpx.Response(200, json=[{
            "sha": "abcdef1234567890", "html_url": "u",
            "commit": {"message": "do thing\n\nbody", "author": {"date": "2026-01-02T00:00:00Z", "name": "Joe"}},
            "author": {"login": "joe"},
        }])
    if path == "/repos/acme/web/releases":
        return httpx.Response(200, json=[{
            "id": 99, "tag_name": "v1.0", "name": "1.0", "published_at": "2026-01-02T00:00:00Z", "author": {"login": "joe"},
        }])
    return httpx.Response(404, json={})


def test_connector_initial_sync_normalizes_all_kinds():
    gh = GitHubClient(StaticToken("t"), http=client_over(_sync_handler))
    connector = GitHubConnector("t", "acme", client=gh)
    events = list(connector.initial_sync())
    kinds = {e.kind for e in events}
    assert kinds == {"pull_request", "issue", "commit", "release"}
    assert all(e.source == Source.GITHUB for e in events)
    pr = next(e for e in events if e.kind == "pull_request")
    assert pr.external_id == "github:acme/web#pr-7"
    assert pr.attributes["labels"] == ["bug"]
    # The issues endpoint's PR entry is filtered out (only issue #3 remains).
    issues = [e for e in events if e.kind == "issue"]
    assert [e.external_id for e in issues] == ["github:acme/web#issue-3"]


def test_connector_incremental_sync_filters_by_cursor():
    gh = GitHubClient(StaticToken("t"), http=client_over(_sync_handler))
    connector = GitHubConnector("t", "acme", client=gh, repos=["acme/web"])
    # Cursor after everything -> nothing new.
    assert list(connector.incremental_sync("2026-06-01T00:00:00Z")) == []


def test_connector_dedup_within_process():
    gh = GitHubClient(StaticToken("t"), http=client_over(_sync_handler))
    connector = GitHubConnector("t", "acme", client=gh, repos=["acme/web"])
    first = list(connector.initial_sync())
    second = list(connector.initial_sync())
    assert len(first) == 4
    assert second == []  # everything already seen


# --- webhooks --------------------------------------------------------------------


def test_signature_roundtrip_and_rejection():
    body = b'{"zen":"hi"}'
    good = sign("s3cret", body)
    assert verify_signature("s3cret", body, good)
    assert not verify_signature("s3cret", body, "sha256=deadbeef")
    assert not verify_signature("s3cret", body, None)
    assert not verify_signature("", body, good)


def test_parse_pull_request_event():
    payload = {"action": "opened", "repository": {"full_name": "acme/web"},
               "pull_request": {"number": 5, "title": "T", "user": {"login": "joe"}, "updated_at": "2026-01-01T00:00:00Z", "labels": []}}
    events = parse_event("pull_request", payload)
    assert len(events) == 1 and events[0].external_id == "github:acme/web#pr-5"
    assert events[0].attributes["action"] == "opened"


def test_parse_push_event_multiple_commits():
    payload = {"repository": {"full_name": "acme/web"}, "ref": "refs/heads/main", "commits": [
        {"id": "aaaaaaaaaaaa1", "message": "one", "author": {"username": "joe"}, "timestamp": "2026-01-01T00:00:00Z"},
        {"id": "bbbbbbbbbbbb2", "message": "two", "author": {"username": "sam"}, "timestamp": "2026-01-01T00:01:00Z"},
    ]}
    events = parse_event("push", payload)
    assert [e.kind for e in events] == ["commit", "commit"]
    assert events[0].attributes["ref"] == "refs/heads/main"


def test_parse_ping_and_unknown_are_empty():
    assert parse_event("ping", {"zen": "x"}) == []
    assert parse_event("membership", {"repository": {"full_name": "acme/web"}}) == []


# --- config factory --------------------------------------------------------------


def test_factory_selects_static_token():
    s = GitHubSettings(org="acme", token="ghp_x")
    connector = build_github_connector(s)
    assert isinstance(connector, GitHubConnector)


def test_factory_none_without_org_or_creds():
    assert build_github_connector(GitHubSettings(token="ghp_x")) is None  # no org
    assert build_github_connector(GitHubSettings(org="acme")) is None  # no creds


def test_factory_prefers_oauth_over_token():
    s = GitHubSettings(org="acme", token="ghp_x", client_id="cid", client_secret="cs", oauth_refresh_token="rt")
    provider = s.token_provider()
    assert isinstance(provider, RefreshingOAuthToken)
