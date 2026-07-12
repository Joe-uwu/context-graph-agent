"""The 'deploy will fail' scenario.

Five source events that, individually, look ordinary. Only when the graph joins them
does the risk appear: a deployment blocked by a ticket blocked by an open incident that
affects the service a just-merged PR changed, discussed in an on-call thread. Natural
keys are shared across sources so the entities merge into single nodes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cortex.contracts.enums import Source
from cortex.contracts.payloads import RawEvent

ORG_ID = "org_demo"


def deploy_will_fail_scenario(now: datetime | None = None) -> list[RawEvent]:
    now = now or datetime.now(timezone.utc)
    deploy_at = (now + timedelta(hours=2)).isoformat()
    incident_opened = (now - timedelta(hours=3)).isoformat()

    pagerduty = RawEvent(
        source=Source.PAGERDUTY, kind="incident_triggered", external_id="pd:INC-2207",
        occurred_at=now - timedelta(hours=3), title="Elevated 5xx on billing",
        attributes={
            "number": "INC-2207", "severity": "SEV2", "status": "triggered",
            "service": "billing", "criticality": "tier0", "assignee": "Dana Ito",
        },
    )
    jira = RawEvent(
        source=Source.JIRA, kind="ticket_updated", external_id="jira:PAY-1193",
        occurred_at=now - timedelta(minutes=40), title="Reconcile billing client retries",
        attributes={
            "key": "PAY-1193", "status": "In Progress", "priority": "High", "age_days": 6,
            "blocks": ["checkout-api"], "blocked_by_incidents": ["INC-2207"],
            "env": "prod", "deploy_scheduled_at": deploy_at,
        },
    )
    github = RawEvent(
        source=Source.GITHUB, kind="pr_merged", external_id="github:pr:checkout-api#482",
        occurred_at=now - timedelta(minutes=20), actor="arjun",
        title="Bump billing-client, tighten retry budget",
        body="Depends on PAY-1193. Touches the billing integration path.",
        attributes={"number": 482, "repo": "checkout-api", "touches_services": ["billing"]},
    )
    slack = RawEvent(
        source=Source.SLACK, kind="thread_message", external_id="slack:C0PAY:169",
        occurred_at=now - timedelta(minutes=15), actor="Dana Ito",
        title="on-call sync", body="INC-2207 still open, retries hammering billing. PAY-1193 tracks the fix.",
        attributes={"channel": "#payments-oncall", "permalink": "https://slack/x", "message_count": 12},
    )
    calendar = RawEvent(
        source=Source.CALENDAR, kind="meeting_scheduled", external_id="cal:evt:8821",
        occurred_at=now, title="Payments deploy review",
        attributes={
            "start": (now + timedelta(hours=1)).isoformat(),
            "end": (now + timedelta(hours=1, minutes=30)).isoformat(),
            "references_projects": ["Payments Q3"],
        },
    )
    # incident_opened is referenced via attributes above; kept for clarity of timeline.
    _ = incident_opened
    return [pagerduty, jira, github, slack, calendar]
