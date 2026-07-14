"""GNNScorer: urgency scoring via the trained message-passing GNN, behind the scorer port.

Same call shape as the heuristic UrgencyScorer (score(anchor, nodes, edges) -> ScoreResult) and
the same temporal decay + confidence handling, so downstream reasoning thresholds are unchanged.
The GNN supplies the base urgency from the subgraph structure instead of the weighted feature
sum. Weights ship as assets/gnn_urgency.npz; load_default_gnn_scorer returns None if they are
missing so the caller can fall back to the heuristic.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

from cortex.graph_sdk.models import Edge, Node
from cortex.platform.logging import get_logger
from cortex.services.ranking.gnn.features import featurize
from cortex.services.ranking.gnn.model import GNNModel
from cortex.services.ranking.scoring import ScoreResult

log = get_logger("cortex.ranking.gnn")

DEFAULT_WEIGHTS = Path(__file__).resolve().parent.parent / "assets" / "gnn_urgency.npz"


class GNNScorer:
    def __init__(self, model: GNNModel, *, decay_lambda: float = 0.02) -> None:
        self._model = model
        self._lambda = decay_lambda

    def score(self, anchor: Node, nodes: list[Node], edges: list[Edge]) -> ScoreResult:
        X, A, anchor_idx = featurize(anchor, nodes, edges)
        base = self._model.score_one(X, A, anchor_idx)
        decay = math.exp(-self._lambda * _hours_since(anchor.updated_at))
        score = round(base * decay, 4)
        confidence = round(min([e.confidence for e in edges], default=anchor.confidence), 4)
        return ScoreResult(node_id=anchor.id, score=score, confidence=confidence,
                           features={"gnn_base": round(base, 4)})


def load_default_gnn_scorer(path: Path | str = DEFAULT_WEIGHTS) -> GNNScorer | None:
    p = Path(path)
    if not p.exists():
        log.warning("gnn weights not found; caller should fall back", extra={"extra_fields": {"path": str(p)}})
        return None
    try:
        return GNNScorer(GNNModel.load(str(p)))
    except Exception as exc:  # noqa: BLE001 - bad/mismatched weights -> heuristic fallback
        log.warning("failed to load gnn weights", extra={"extra_fields": {"error": str(exc)}})
        return None


def _hours_since(ts: datetime) -> float:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - ts).total_seconds() / 3600.0, 0.0)
