"""Load the UCI 'Incident management process enriched event log' into training graphs.

Real ServiceNow incident data (24,918 incidents / 141,712 event rows), anonymized, published by
UCI: http://archive.ics.uci.edu/ml/datasets/Incident+management+process+enriched+event+log

Each incident is collapsed to its most-updated event row and turned into a small graph the GNN
can score: a Service anchor (the affected configuration item), the Incident (carrying the real
impact as severity), the reporting Person, and the owning support Team. The training label is the
incident's real ``priority`` (or ``urgency``) field mapped to [0, 1] — so the model learns from
labels a real incident-management system actually assigned, not a synthetic teacher.

Missing values are coded ``?`` in this dataset and are handled. The loader has no heavyweight
dependencies (plain csv); numpy only enters at training time via the featurizer.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone

from cortex.contracts.enums import EdgeType, NodeLabel, Source
from cortex.graph_sdk.models import Edge, Node

# Real label fields -> urgency target in [0, 1]. priority is the system-calculated field
# (Critical/High/Moderate/Low); urgency is the user-reported 1/2/3.
LABEL_MAPS = {
    "priority": {1: 0.95, 2: 0.75, 3: 0.45, 4: 0.20, 5: 0.10},
    "urgency": {1: 0.90, 2: 0.50, 3: 0.15},
    "impact": {1: 0.90, 2: 0.50, 3: 0.15},
}
_IMPACT_SEVERITY = {1: "SEV1", 2: "SEV2", 3: "SEV3"}
_now = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _level(value: str | None) -> int | None:
    """Parse a coded level like '1 - High' / '2 - Medium' -> 1 / 2. '?' or blank -> None."""
    if not value or value.strip() in ("", "?"):
        return None
    head = value.strip().split(" ")[0].rstrip("-").strip()
    try:
        return int(head)
    except ValueError:
        return None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return None if v in ("", "?") else v


def _node(nid: str, label: NodeLabel, source: Source, **props) -> Node:
    return Node(id=nid, org_id="servicenow", label=label, natural_key=nid, source=source.value,
                properties={k: v for k, v in props.items() if v is not None},
                confidence=1.0, created_at=_now, updated_at=_now)


def _edge(t: EdgeType, a: str, b: str) -> Edge:
    return Edge(id=f"{t.value}:{a}:{b}", org_id="servicenow", type=t, from_id=a, to_id=b,
                confidence=1.0, valid_from=_now)


def _row_to_graph(number: str, row: dict, label_field: str):
    label_level = _level(row.get(label_field))
    if label_level is None or label_level not in LABEL_MAPS[label_field]:
        return None
    label = LABEL_MAPS[label_field][label_level]

    ci = _clean(row.get("cmdb_ci"))
    svc_key = f"svc:{ci}" if ci else f"svc:{number}"
    criticality = None  # not present in the log; left to the model to infer from context
    anchor = _node(svc_key, NodeLabel.SERVICE, Source.GITHUB, criticality=criticality)

    nodes = [anchor]
    edges: list[Edge] = []

    impact = _level(row.get("impact"))
    inc = _node(f"inc:{number}", NodeLabel.INCIDENT, Source.PAGERDUTY,
                severity=_IMPACT_SEVERITY.get(impact) if impact else None,
                reassignment_count=_int(row.get("reassignment_count")),
                reopen_count=_int(row.get("reopen_count")),
                made_sla=row.get("made_sla"),
                category=_clean(row.get("category")))
    nodes.append(inc)
    edges.append(_edge(EdgeType.AFFECTS, inc.id, anchor.id))

    caller = _clean(row.get("caller_id"))
    if caller:
        p = _node(f"person:{caller}", NodeLabel.PERSON, Source.GITHUB)
        nodes.append(p)
        edges.append(_edge(EdgeType.TRIGGERS, p.id, inc.id))

    group = _clean(row.get("assignment_group"))
    if group:
        team = _node(f"team:{group}", NodeLabel.TEAM, Source.GITHUB)
        nodes.append(team)
        edges.append(_edge(EdgeType.OWNS, team.id, anchor.id))

    return anchor, nodes, edges, label


def _int(value: str | None) -> int | None:
    v = _clean(value)
    if v is None:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def load_incident_event_log(csv_path: str, *, label_field: str = "priority",
                            limit: int | None = None) -> list[tuple]:
    """Return [(anchor, nodes, edges, label), ...] from the UCI incident event log CSV.

    Each incident (``number``) is collapsed to the row with the highest ``sys_mod_count`` (the
    most complete state). ``label_field`` is one of priority / urgency / impact.
    """
    if label_field not in LABEL_MAPS:
        raise ValueError(f"label_field must be one of {sorted(LABEL_MAPS)}")

    best: dict[str, dict] = {}
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            number = _clean(row.get("number"))
            if not number:
                continue
            mods = _int(row.get("sys_mod_count")) or 0
            prev = best.get(number)
            if prev is None or mods >= (_int(prev.get("sys_mod_count")) or 0):
                best[number] = row

    samples: list[tuple] = []
    for number, row in best.items():
        graph = _row_to_graph(number, row, label_field)
        if graph is not None:
            samples.append(graph)
        if limit is not None and len(samples) >= limit:
            break
    return samples
