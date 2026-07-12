"""GitHub connector: OAuth/App auth, paginated + rate-limited REST client, incremental
sync, and webhook ingestion. See README.md in this package."""

from cortex.services.ingestion.connectors.github.auth import (
    GitHubApp,
    GitHubAuthError,
    OAuthApp,
    OAuthTokens,
    RefreshingOAuthToken,
    StaticToken,
    TokenProvider,
)
from cortex.services.ingestion.connectors.github.client import GitHubClient
from cortex.services.ingestion.connectors.github.config import (
    GitHubSettings,
    build_github_connector,
)
from cortex.services.ingestion.connectors.github.connector import GitHubConnector
from cortex.services.ingestion.connectors.github.webhooks import (
    SUPPORTED_EVENTS,
    parse_event,
    sign,
    verify_signature,
)

__all__ = [
    "GitHubApp",
    "GitHubAuthError",
    "OAuthApp",
    "OAuthTokens",
    "RefreshingOAuthToken",
    "StaticToken",
    "TokenProvider",
    "GitHubClient",
    "GitHubConnector",
    "GitHubSettings",
    "build_github_connector",
    "parse_event",
    "verify_signature",
    "sign",
    "SUPPORTED_EVENTS",
]
