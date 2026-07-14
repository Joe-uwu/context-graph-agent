"""Urgency scoring model (docs/design/urgency-scoring.md).

Weighted feature sum → logistic squash → temporal decay. Features are computed over the
k-hop neighborhood so relational signals (blocked dependencies, blast radius,
cross-source corroboration) are available. Confidence is the min edge confidence along
the evidence, kept separate from the score.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from cortex.contracts.enums import EdgeType, NodeLabel
from cortex.graph_sdk.models import Edge, Node
from cortex.platform.logging import get_logger

log = get_logger("cortex.ranking")

_SEVERITY = {"SEV1": 1.0, "SEV2": 0.7, "SEV3": 0.4, "SEV4": 0.2}
_CRITICALITY = {"tier0": 1.0, "tier1": 0.75, "tier2": 0.5, "tier3": 0.25}
_PRIORITY = {"Blocker": 1.0, "Critical": 0.85, "High": 0.7, "Medium": 0.45, "Low": 0.2}


def default_weights() -> dict[str, float]:
    return {
        "incident_severity": 0.95,
        "blocked_dependency_count": 0.85,
        "deployment_proximity": 0.80,
        "service_criticality": 0.75,
        "blast_radius": 0.70,
        "ticket_priority": 0.55,
        "discussion_velocity": 0.50,
        "cross_source_corroboration": 0.50,
        "recent_incident_density": 0.45,
        "repo_importance": 0.40,
        "incident_age": 0.40,
        "meeting_proximity": 0.35,
        "ticket_age": 0.30,
        "owner_workload": -0.30,
    }


@dataclass
class ScoreResult:
    node_id: str
    score: float
    confidence: float
    features: dict[str, float] = field(default_factory=dict)


class UrgencyScorer:
    def __init__(
        self, weights: dict[str, float] | None = None,
        *, k: float = 8.0, bias: float = 0.35, decay_lambda: float = 0.02,
    ) -> None:
        self._w = weights or default_weights()
        self._k = k
        self._bias = bias
        self._lambda = decay_lambda
        # Normalize the weighted sum by the positive weight mass so the operating point
        # (bias) is independent of how many features exist or how they are weighted.
        self._pos_mass = sum(w for w in self._w.values() if w > 0) or 1.0

    @property
    def weights(self) -> dict[str, float]:
        return dict(self._w)

    def score(self, anchor: Node, nodes: list[Node], edges: list[Edge]) -> ScoreResult:
        f = self._features(anchor, nodes, edges)
        raw = sum(self._w.get(name, 0.0) * value for name, value in f.items())
        norm = raw / self._pos_mass
        base = 1.0 / (1.0 + math.exp(-self._k * (norm - self._bias)))
        decay = math.exp(-self._lambda * _hours_since(anchor.updated_at))
        score = round(base * decay, 4)
        confidence = round(min([e.confidence for e in edges], default=anchor.confidence), 4)
        return ScoreResult(node_id=anchor.id, score=score, confidence=confidence, features=f)

    def _features(self, anchor: Node, nodes: list[Node], edges: list[Edge]) -> dict[str, float]:
        by_id = {n.id: n for n in nodes}
        by_label: dict[NodeLabel, list[Node]] = {}
        for n in nodes:
            by_label.setdefault(n.label, []).append(n)

        incidents = by_label.get(NodeLabel.INCIDENT, [])
        services = by_label.get(NodeLabel.SERVICE, [])
        tickets = by_label.get(NodeLabel.TICKET, [])
        deployments = by_label.get(NodeLabel.DEPLOYMENT, [])
        threads = by_label.get(NodeLabel.SLACK_THREAD, [])
        meetings = by_label.get(NodeLabel.MEETING, [])

        f: dict[str, float] = {
            "incident_severity": max(
                (_SEVERITY.get(str(i.properties.get("severity")), 0.0) for i in incidents), default=0.0
            ),
            "service_criticality": max(
                (_CRITICALITY.get(str(s.properties.get("criticality")), 0.5) for s in services),
                default=0.0,
            ),
            "ticket_priority": max(
                (_PRIORITY.get(str(t.properties.get("priority")), 0.4) for t in tickets), default=0.0
            ),
            "blocked_dependency_count": _norm_count(
                sum(1 for e in edges if e.type == EdgeType.BLOCKS), cap=3
            ),
            "blast_radius": _norm_count(len(services), cap=5),
            "deployment_proximity": max(
                (_proximity(d.properties.get("scheduled_at")) for d in deployments), default=0.0
            ),
            "meeting_proximity": max(
                (_proximity(m.properties.get("start")) for m in meetings), default=0.0
            ),
            "discussion_velocity": _norm_count(
                sum(int(t.properties.get("message_count", 1)) for t in threads), cap=20
            ),
            "cross_source_corroboration": _norm_count(
                len({n.source for n in by_id.values()}), cap=4
            ),
            "recent_incident_density": _norm_count(len(incidents), cap=3),
            "repo_importance": 0.4 if by_label.get(NodeLabel.REPOSITORY) else 0.0,
            "incident_age": max(
                (_age_frac(i.properties.get("opened_at"), cap_h=12) for i in incidents), default=0.0
            ),
            "ticket_age": max(
                (min(float(t.properties.get("age_days", 0)) / 14.0, 1.0) for t in tickets), default=0.0
            ),
            "owner_workload": 0.0,  # populated from cross-node owner load in production
        }
        return {k: round(v, 4) for k, v in f.items()}


def _hours_since(ts: datetime) -> float:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - ts).total_seconds() / 3600.0, 0.0)


def _norm_count(n: int, *, cap: int) -> float:
    return min(n / cap, 1.0) if cap else 0.0


def _proximity(scheduled_at: object) -> float:
    """1.0 when the event is now/soon, decaying to 0 by ~48h out."""
    if not scheduled_at:
        return 0.0
    try:
        when = datetime.fromisoformat(str(scheduled_at))
    except ValueError:
        return 0.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    hours = (when - datetime.now(timezone.utc)).total_seconds() / 3600.0
    if hours <= 0:
        return 1.0
    return max(0.0, 1.0 - hours / 48.0)


def _age_frac(opened_at: object, *, cap_h: float) -> float:
    if not opened_at:
        return 0.0
    try:
        when = datetime.fromisoformat(str(opened_at))
    except ValueError:
        return 0.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return min(_hours_since(when) / cap_h, 1.0)


def build_scorer(settings=None):
    """Select the urgency scorer. "gnn" loads the trained message-passing GNN (numpy) behind
    the same port; anything else — or missing/again bad weights — uses the heuristic model."""
    kind = getattr(settings, "scorer_model", "heuristic") if settings is not None else "heuristic"
    if kind == "gnn":
        try:
            from cortex.services.ranking.gnn.scorer import load_default_gnn_scorer

            gnn = load_default_gnn_scorer()
            if gnn is not None:
                log.info("urgency scorer: gnn")
                return gnn
        except Exception as exc:  # noqa: BLE001 - numpy/weights problem -> heuristic
            log.warning("gnn scorer unavailable, using heuristic",
                        extra={"extra_fields": {"error": str(exc)}})
        log.warning("gnn weights unavailable, using heuristic scorer")
    return UrgencyScorer()
