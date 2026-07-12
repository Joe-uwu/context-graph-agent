"""GitHub connector configuration and factory.

Reads ``CORTEX_GITHUB_*`` environment variables and picks the strongest auth strategy the
credentials allow: a GitHub App installation (app id + private key + installation id) >
OAuth refresh (client id/secret + refresh token) > a static token/PAT. Returns None when no
usable credentials are configured, so the ingestion service stays up on the mock twin.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from cortex.platform.logging import get_logger
from cortex.services.ingestion.connectors.github.auth import (
    GitHubApp,
    OAuthApp,
    OAuthTokens,
    RefreshingOAuthToken,
    StaticToken,
    TokenProvider,
)
from cortex.services.ingestion.connectors.github.client import GitHubClient
from cortex.services.ingestion.connectors.github.connector import GitHubConnector

log = get_logger("cortex.ingestion.github")


class GitHubSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CORTEX_GITHUB_", extra="ignore")

    org: str = ""
    repos: str = ""  # comma-separated "repo" or "owner/repo"; empty = every org repo
    api_base_url: str = "https://api.github.com"

    # Static token / PAT.
    token: str = ""

    # GitHub App installation auth.
    app_id: str = ""
    private_key: str = ""
    private_key_path: str = ""
    installation_id: str = ""

    # OAuth web-flow auth.
    client_id: str = ""
    client_secret: str = ""
    oauth_access_token: str = ""
    oauth_refresh_token: str = ""

    # Webhook receiver.
    webhook_secret: str = ""

    def repo_list(self) -> list[str]:
        return [r.strip() for r in self.repos.split(",") if r.strip()]

    def _private_key_pem(self) -> str:
        if self.private_key:
            return self.private_key
        if self.private_key_path:
            return Path(self.private_key_path).read_text()
        return ""

    def token_provider(self) -> TokenProvider | None:
        if self.app_id and self.installation_id and self._private_key_pem():
            return GitHubApp(self.app_id, self._private_key_pem(), self.installation_id)
        if self.client_id and self.client_secret and self.oauth_refresh_token:
            app = OAuthApp(self.client_id, self.client_secret)
            tokens = OAuthTokens(
                access_token=self.oauth_access_token,
                refresh_token=self.oauth_refresh_token,
                expires_at=0.0,  # force a refresh on first use if no access token is set
            )
            return RefreshingOAuthToken(app, tokens)
        if self.token:
            return StaticToken(self.token)
        return None


def build_github_connector(settings: GitHubSettings | None = None) -> GitHubConnector | None:
    settings = settings or GitHubSettings()
    if not settings.org:
        return None
    provider = settings.token_provider()
    if provider is None:
        return None
    client = GitHubClient(provider, base_url=settings.api_base_url)
    log.info("github connector configured", extra={"extra_fields": {"org": settings.org}})
    return GitHubConnector(provider, settings.org, client=client, repos=settings.repo_list() or None)
