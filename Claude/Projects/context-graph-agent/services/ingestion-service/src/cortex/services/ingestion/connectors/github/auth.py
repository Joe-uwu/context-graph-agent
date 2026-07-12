"""GitHub authentication strategies, all behind the TokenProvider protocol.

- StaticToken: a personal access token or a pre-minted installation token.
- OAuthApp + RefreshingOAuthToken: the OAuth authorization-code (web) flow — build the
  authorize URL, exchange the code for an access token, and refresh it. No private key.
- GitHubApp: mint short-lived installation access tokens from the app id + RSA private key
  (RS256 app JWT -> POST /app/installations/{id}/access_tokens), cached until near expiry.

The REST client only depends on TokenProvider.token(), so it does not care which strategy
minted the token.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable
from urllib.parse import urlencode

import httpx

GITHUB_API = "https://api.github.com"
OAUTH_BASE = "https://github.com/login/oauth"


class GitHubAuthError(RuntimeError):
    """Raised when GitHub rejects a token exchange or refresh."""


@runtime_checkable
class TokenProvider(Protocol):
    def token(self) -> str:
        """Return a currently-valid bearer token, refreshing/minting as needed."""


@dataclass
class StaticToken:
    """A personal access token or a pre-minted installation token."""

    value: str

    def token(self) -> str:
        if not self.value:
            raise GitHubAuthError("empty GitHub token")
        return self.value


@dataclass
class OAuthTokens:
    access_token: str
    token_type: str = "bearer"
    scope: str = ""
    refresh_token: str | None = None
    expires_at: float | None = None  # epoch seconds
    refresh_token_expires_at: float | None = None

    @classmethod
    def from_response(cls, data: dict, *, now: float | None = None) -> OAuthTokens:
        if "error" in data:
            raise GitHubAuthError(data.get("error_description") or data["error"])
        now = time.time() if now is None else now
        expires_in = data.get("expires_in")
        refresh_expires_in = data.get("refresh_token_expires_in")
        return cls(
            access_token=data["access_token"],
            token_type=data.get("token_type", "bearer"),
            scope=data.get("scope", ""),
            refresh_token=data.get("refresh_token"),
            expires_at=(now + float(expires_in)) if expires_in else None,
            refresh_token_expires_at=(now + float(refresh_expires_in)) if refresh_expires_in else None,
        )

    def expired(self, *, skew: float = 60.0, now: float | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (time.time() if now is None else now) >= self.expires_at - skew

    def token(self) -> str:
        return self.access_token


class OAuthApp:
    """OAuth App / GitHub App user-to-server web flow."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        redirect_uri: str | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._http = http or httpx.Client(timeout=30.0)

    def authorize_url(
        self, *, state: str, scopes: tuple[str, ...] = (), login: str | None = None
    ) -> str:
        params: dict[str, str] = {"client_id": self._client_id, "state": state}
        if scopes:
            params["scope"] = " ".join(scopes)
        if self._redirect_uri:
            params["redirect_uri"] = self._redirect_uri
        if login:
            params["login"] = login
        return f"{OAUTH_BASE}/authorize?{urlencode(params)}"

    def exchange_code(self, code: str) -> OAuthTokens:
        return self._post_token({"grant_type": "authorization_code", "code": code})

    def refresh(self, refresh_token: str) -> OAuthTokens:
        return self._post_token(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    def _post_token(self, payload: dict) -> OAuthTokens:
        body = {
            **payload,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._redirect_uri and "redirect_uri" not in body:
            body["redirect_uri"] = self._redirect_uri
        resp = self._http.post(
            f"{OAUTH_BASE}/access_token", data=body, headers={"Accept": "application/json"}
        )
        resp.raise_for_status()
        return OAuthTokens.from_response(resp.json())


class RefreshingOAuthToken:
    """TokenProvider that auto-refreshes a user-to-server token before it expires."""

    def __init__(self, app: OAuthApp, tokens: OAuthTokens) -> None:
        self._app = app
        self._tokens = tokens

    @property
    def tokens(self) -> OAuthTokens:
        return self._tokens

    def token(self) -> str:
        if self._tokens.expired() and self._tokens.refresh_token:
            self._tokens = self._app.refresh(self._tokens.refresh_token)
        return self._tokens.access_token


class GitHubApp:
    """Mint installation access tokens from a GitHub App id + RSA private key."""

    def __init__(
        self,
        app_id: str | int,
        private_key_pem: str,
        installation_id: str | int,
        *,
        http: httpx.Client | None = None,
        clock=time.time,
    ) -> None:
        self._app_id = str(app_id)
        self._private_key = private_key_pem
        self._installation_id = str(installation_id)
        self._http = http or httpx.Client(timeout=30.0)
        self._clock = clock
        self._cached: tuple[str, float] | None = None  # (token, expiry_epoch)

    def app_jwt(self) -> str:
        """RS256-signed app JWT (10 min max lifetime, 60s clock-skew allowance)."""
        import jwt  # PyJWT[crypto]; provided by the ingestion 'github' extra

        now = int(self._clock())
        payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": self._app_id}
        token = jwt.encode(payload, self._private_key, algorithm="RS256")
        return token.decode() if isinstance(token, bytes) else token

    def installation_token(self) -> str:
        now = self._clock()
        if self._cached and now < self._cached[1] - 60:
            return self._cached[0]
        resp = self._http.post(
            f"{GITHUB_API}/app/installations/{self._installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {self.app_jwt()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        expiry = _iso_to_epoch(data["expires_at"])
        self._cached = (data["token"], expiry)
        return data["token"]

    def token(self) -> str:
        return self.installation_token()


def _iso_to_epoch(value: str) -> float:
    text = str(value).replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()
