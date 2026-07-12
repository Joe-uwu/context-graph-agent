"""Enumerations shared across the platform.

Node labels and edge types mirror docs/data/graph-model.md. Keeping them here means
the graph model, the extractors, and the API all reference one definition.
"""

from __future__ import annotations

from enum import Enum


class Source(str, Enum):
    GITHUB = "github"
    SLACK = "slack"
    JIRA = "jira"
    NOTION = "notion"
    CALENDAR = "calendar"
    PAGERDUTY = "pagerduty"
    DERIVED = "derived"


class NodeLabel(str, Enum):
    PERSON = "Person"
    TEAM = "Team"
    REPOSITORY = "Repository"
    SERVICE = "Service"
    PULL_REQUEST = "PullRequest"
    ISSUE = "Issue"
    COMMIT = "Commit"
    RELEASE = "Release"
    DEPLOYMENT = "Deployment"
    TICKET = "Ticket"
    SPRINT = "Sprint"
    INCIDENT = "Incident"
    ALERT = "Alert"
    SLACK_THREAD = "SlackThread"
    SLACK_MESSAGE = "SlackMessage"
    CHANNEL = "Channel"
    NOTION_PAGE = "NotionPage"
    PROJECT = "Project"
    TASK = "Task"
    MEETING = "Meeting"
    DEPENDENCY = "Dependency"
    TECHNOLOGY = "Technology"
    DOCUMENT = "Document"


class EdgeType(str, Enum):
    OWNS = "OWNS"
    MEMBER_OF = "MEMBER_OF"
    AUTHORED = "AUTHORED"
    REVIEWS = "REVIEWS"
    TOUCHES = "TOUCHES"
    REFERENCES = "REFERENCES"
    DEPENDS_ON = "DEPENDS_ON"
    BLOCKS = "BLOCKS"
    DISCUSSES = "DISCUSSES"
    AFFECTS = "AFFECTS"
    TRIGGERS = "TRIGGERS"
    CONTAINS = "CONTAINS"
    DEPLOYS = "DEPLOYS"
    CALLS = "CALLS"
    BELONGS_TO = "BELONGS_TO"
    MENTIONS = "MENTIONS"
    ALIAS_OF = "ALIAS_OF"


class ChangeKind(str, Enum):
    NODE_UPSERTED = "node_upserted"
    EDGE_UPSERTED = "edge_upserted"
    EDGE_CLOSED = "edge_closed"


class DiscoveredBy(str, Enum):
    RULE = "rule"
    EMBEDDING = "embedding"
    LLM = "llm"


class NotificationChannel(str, Enum):
    DASHBOARD = "dashboard"
    SLACK = "slack"
    EMAIL = "email"
    WEBHOOK = "webhook"
    DIGEST = "digest"


class UserActionType(str, Enum):
    ACK = "ack"
    DISMISS = "dismiss"
    SNOOZE = "snooze"
