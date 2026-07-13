"""LLM worker: consume risk.scored, gather evidence, reason, emit reasoning.produced."""

from __future__ import annotations

from cortex.contracts import Event, Topic, new_event
from cortex.contracts.payloads import RiskScored
from cortex.platform.bus import EventBus
from cortex.platform.logging import get_logger
from cortex.platform.observability import METRICS
from cortex.services.llm.reasoning import Reasoner
from cortex.services.retrieval.service import RetrievalService

log = get_logger("cortex.llm")

PRODUCER = "llm-service@0.1.0"


class LlmWorker:
    def __init__(
        self, bus: EventBus, retrieval: RetrievalService,
        *, reasoner: Reasoner | None = None, evidence_hops: int = 3,
    ) -> None:
        self._bus = bus
        self._retrieval = retrieval
        if reasoner is None:
            from cortex.services.llm.graph import GraphReasoner

            reasoner = GraphReasoner()
        self._reasoner = reasoner
        self._hops = evidence_hops
        bus.subscribe(Topic.RISK_SCORED, self.handle, group="llm-service")

    def handle(self, event: Event) -> None:
        risk = RiskScored.model_validate(event.payload)
        evidence = self._retrieval.gather_evidence(
            org_id=event.org_id, node_id=risk.node_id, hops=self._hops
        )
        if evidence is None:
            log.warning("no evidence", extra={"extra_fields": {"node_id": risk.node_id}})
            return
        reasoning = self._reasoner.reason(evidence, risk.score)
        METRICS.inc("cortex_events_processed_total", service="llm-service")
        self._bus.publish(
            Topic.REASONING_PRODUCED,
            new_event(
                org_id=event.org_id, type="reasoning.produced", producer=PRODUCER,
                trace_id=event.trace_id, payload=reasoning,
            ),
        )
        log.info("reasoning produced", extra={"extra_fields": {
            "node_id": risk.node_id, "citations": len(reasoning.citations),
            "confidence": reasoning.confidence,
        }})
