"""Typed state threaded through the reasoning graph.

One ReasoningState instance flows from Observe to Notify; each node reads the fields it
needs and writes the fields it produces. Keeping it a dataclass (not free-form dict) makes
every node's contract explicit and lets the nodes be unit-tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cortex.contracts.payloads import Citation, RecommendedAction
from cortex.services.retrieval.service import EvidenceSet


@dataclass
class Finding:
    """A single grounded observation extracted from the evidence subgraph."""

    text: str
    edge_id: str | None = None
    node_ids: list[str] = field(default_factory=list)
    weight: int = 99


@dataclass
class ReasoningState:
    # --- inputs (Observe) ---
    org_id: str
    node_id: str
    risk_score: float

    # --- Retrieve ---
    evidence: EvidenceSet | None = None

    # --- Verify ---
    verified: bool = False
    verify_reason: str = ""

    # --- GraphTraverse ---
    findings: list[Finding] = field(default_factory=list)
    incidents: list = field(default_factory=list)
    services: list = field(default_factory=list)
    owners: list = field(default_factory=list)

    # --- Reason ---
    summary: str = ""
    explanation: str = ""

    # --- Ground ---
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 0.0

    # --- Explain ---
    narrative: str = ""

    # --- Recommend ---
    actions: list[RecommendedAction] = field(default_factory=list)

    # --- Notify ---
    should_notify: bool = False
    channel_hint: str = "digest"

    # --- control / meta ---
    halted: bool = False
    halt_reason: str = ""
    trace: list[str] = field(default_factory=list)

    def halt(self, reason: str) -> "ReasoningState":
        self.halted = True
        self.halt_reason = reason
        return self
