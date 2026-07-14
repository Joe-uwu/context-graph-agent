"""ranking-service: continuous urgency scoring over changed subgraphs.

A transparent weighted model (explainable by construction) scores the k-hop
neighborhood of each changed node; cost scales with churn, not graph size. Nodes that
cross the reasoning threshold emit risk.scored. See docs/design/urgency-scoring.md.
Distributed execution uses Ray in production (ADR-0011); the reference build scores
in-process.
"""

from cortex.services.ranking.scoring import (
    ScoreResult,
    UrgencyScorer,
    build_scorer,
    default_weights,
)

__all__ = ["ScoreResult", "UrgencyScorer", "build_scorer", "default_weights"]
