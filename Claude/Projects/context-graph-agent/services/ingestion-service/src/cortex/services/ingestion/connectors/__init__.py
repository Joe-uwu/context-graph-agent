"""Connector implementations: one mock twin plus real connectors per source."""

from cortex.services.ingestion.connectors.github import GitHubConnector
from cortex.services.ingestion.connectors.mock import MockConnector
from cortex.services.ingestion.connectors.real_sources import (
    CalendarConnector,
    JiraConnector,
    NotionConnector,
    PagerDutyConnector,
    SlackConnector,
)

__all__ = [
    "MockConnector", "GitHubConnector", "SlackConnector", "JiraConnector",
    "NotionConnector", "CalendarConnector", "PagerDutyConnector",
]
