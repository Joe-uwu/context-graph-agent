"""Deterministic extraction rules per source event kind.

Each rule maps a RawEvent to typed nodes and edges with confidence 1.0. Fuzzy links
(which service a PR touches beyond what is stated, what a thread is about) are left to
the LLM tier; here we only assert what the source states outright. Ticket/incident
references found by regex in free text are emitted as edges (still deterministic — the
id is literally present in the text).
"""

from __future__ import annotations

import re
from collections.abc import Callable

from cortex.contracts.enums import DiscoveredBy, EdgeType, NodeLabel, Source
from cortex.contracts.payloads import EntitiesExtracted, ExtractedEdge, ExtractedNode, RawEvent

_JIRA_KEY = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
_INCIDENT = re.compile(r"\b(INC-\d+)\b")

NodeFn = Callable[..., str]
EdgeFn = Callable[..., None]


def extract(raw: RawEvent) -> EntitiesExtracted:
    nodes: list[ExtractedNode] = []
    edges: list[ExtractedEdge] = []
    a = raw.attributes

    def node(label: NodeLabel, nk: str, **props: object) -> str:
        nodes.append(ExtractedNode(label=label, natural_key=nk, source=raw.source, properties=props))
        return nk

    def edge(t: EdgeType, frm: str, to: str, conf: float = 1.0) -> None:
        edges.append(ExtractedEdge(type=t, from_key=frm, to_key=to, confidence=conf))

    if raw.source == Source.GITHUB and raw.kind == "pr_merged":
        pr = node(NodeLabel.PULL_REQUEST, raw.external_id, title=raw.title, state="merged",
                  number=a.get("number"))
        if raw.actor:
            person = node(NodeLabel.PERSON, f"person:{raw.actor}", display_name=raw.actor)
            edge(EdgeType.AUTHORED, person, pr)
        if a.get("repo"):
            repo = node(NodeLabel.REPOSITORY, f"repo:{a['repo']}", name=a["repo"])
            edge(EdgeType.REFERENCES, pr, repo)
        for svc_name in a.get("touches_services", []):
            svc = node(NodeLabel.SERVICE, f"service:{svc_name}", name=svc_name)
            edge(EdgeType.TOUCHES, pr, svc)
        _link_text_refs(raw, pr, edge, node)

    elif raw.source == Source.JIRA and raw.kind == "ticket_updated":
        ticket = node(NodeLabel.TICKET, raw.external_id, key=a.get("key"), status=a.get("status"),
                      priority=a.get("priority"), title=raw.title, age_days=a.get("age_days", 0))
        for blocked in a.get("blocks", []):
            tgt = node(NodeLabel.DEPLOYMENT, f"deploy:{blocked}", env=a.get("env", "prod"),
                       service=blocked, scheduled_at=a.get("deploy_scheduled_at"))
            edge(EdgeType.BLOCKS, ticket, tgt)
        for inc in a.get("blocked_by_incidents", []):
            incident = node(NodeLabel.INCIDENT, f"pd:{inc}", number=inc)
            edge(EdgeType.BLOCKS, incident, ticket)

    elif raw.source == Source.PAGERDUTY and raw.kind == "incident_triggered":
        inc = node(NodeLabel.INCIDENT, raw.external_id, number=a.get("number"),
                   severity=a.get("severity"), status=a.get("status", "triggered"),
                   opened_at=raw.occurred_at.isoformat())
        svc_key: str | None = None
        if a.get("service"):
            svc_key = node(NodeLabel.SERVICE, f"service:{a['service']}", name=a["service"],
                           criticality=a.get("criticality", "tier1"))
            edge(EdgeType.AFFECTS, inc, svc_key)
        if a.get("assignee") and svc_key:
            person = node(NodeLabel.PERSON, f"person:{a['assignee']}", display_name=a["assignee"])
            edge(EdgeType.OWNS, person, svc_key)

    elif raw.source == Source.SLACK and raw.kind == "thread_message":
        thread = node(NodeLabel.SLACK_THREAD, raw.external_id, channel=a.get("channel"),
                      permalink=a.get("permalink"), message_count=a.get("message_count", 1))
        _link_text_refs(raw, thread, edge, node, discussion=True)

    elif raw.source == Source.CALENDAR and raw.kind == "meeting_scheduled":
        meeting = node(NodeLabel.MEETING, raw.external_id, title=raw.title,
                       start=a.get("start"), end=a.get("end"))
        for proj in a.get("references_projects", []):
            p = node(NodeLabel.PROJECT, f"project:{proj}", name=proj)
            edge(EdgeType.DISCUSSES, meeting, p, conf=0.9)

    elif raw.source == Source.NOTION and raw.kind == "page_updated":
        node(NodeLabel.NOTION_PAGE, raw.external_id, title=raw.title, url=a.get("url"))

    return EntitiesExtracted(source_event_id=raw.external_id, nodes=nodes, edges=edges)


def _link_text_refs(
    raw: RawEvent, from_key: str, edge: EdgeFn, node: NodeFn, discussion: bool = False
) -> None:
    text = f"{raw.title or ''} {raw.body or ''}"
    rel = EdgeType.DISCUSSES if discussion else EdgeType.REFERENCES
    for match in _JIRA_KEY.findall(text):
        ticket = node(NodeLabel.TICKET, f"jira:{match}", key=match)
        edge(rel, from_key, ticket)
    for match in _INCIDENT.findall(text):
        inc = node(NodeLabel.INCIDENT, f"pd:{match}", number=match)
        edge(rel, from_key, inc)


# The LLM tier would add edges like TOUCHES/DEPENDS_ON at sub-1.0 confidence.
LLM_DISCOVERED = DiscoveredBy.LLM
