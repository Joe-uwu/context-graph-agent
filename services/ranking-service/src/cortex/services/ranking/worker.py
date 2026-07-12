"""Ranking worker: consume graph.changes, score changed subgraphs, emit risk.scored.

In production the per-subgraph scoring is fanned across Ray workers (ADR-0011); here it
runs in-process. Only nodes crossing `reason_at` emit risk.scored, which bounds how
often the LLM stage runs.
"""

from __future__ import annotations

from cortex.contracts import Event, Topic, new_event
from cortex.contracts.payloads import GraphChanged, RiskScored
from cortex.graph_sdk.repository import GraphRepository
from cortex.platform.bus import EventBus
from cortex.platform.logging import get_logger
from cortex.platform.observability import METRICS
from cortex.services.ranking.scoring import UrgencyScorer

log = get_logger("cortex.ranking")

PRODUCER = "ranking-service@0.1.0"


class RankingWorker:
    def __init__(
        self, bus: EventBus, repo: GraphRepository,
        *, scorer: UrgencyScorer | None = None, reason_at: float = 0.60, hops: int = 2,
    ) -> None:
        self._bus = bus
        self._repo = repo
        self._scorer = scorer or UrgencyScorer()
        self._reason_at = reason_at
        self._hops = hops
        bus.subscribe(Topic.GRAPH_CHANGES, self.handle, group="ranking-service")

    def handle(self, event: Event) -> None:
        change = GraphChanged.model_validate(event.payload)
        org = event.org_id
        # Coalesce duplicates within the batch.
        for node_id in dict.fromkeys(change.changed_node_ids):
            anchor = self._repo.get_node(org_id=org, node_id=node_id)
            if anchor is None:
                continue
            nodes, edges = self._repo.neighborhood(org_id=org, node_id=node_id, hops=self._hops)
            result = self._scorer.score(anchor, nodes, edges)
            self._repo.set_urgency(
                org_id=org, node_id=node_id, score=result.score, features=result.features
            )
            METRICS.inc("cortex_events_processed_total", service="ranking-service")
            METRICS.observe("cortex_risk_score", result.score, service="ranking-service")
            if result.score >= self._reason_at:
                self._bus.publish(
                    Topic.RISK_SCORED,
                    new_event(
                        org_id=org, type="risk.scored", producer=PRODUCER, trace_id=event.trace_id,
                        payload=RiskScored(
                            node_id=node_id, score=result.score,
                            confidence=result.confidence, features=result.features,
                        ),
                    ),
                )
                log.info("risk crossed threshold", extra={"extra_fields": {
                    "node_id": node_id, "score": result.score,
                }})
