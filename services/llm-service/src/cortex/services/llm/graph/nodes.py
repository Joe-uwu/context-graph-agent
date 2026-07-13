"""The nine reasoning nodes.

Each is a pure function ``(state, deps) -> state`` that reads the fields produced by earlier
nodes and writes its own, so it can be unit-tested in isolation. ``deps`` is duck-typed
(ReasoningConfig): nodes read ``deps.retrieval``, ``deps.evidence_hops``,
``deps.max_clauses``, ``deps.interrupt_at`` with sensible fallbacks.
"""

from __future__ import annotations

from cortex.contracts.enums import NodeLabel
from cortex.contracts.payloads import Citation, RecommendedAction
from cortex.services.llm.graph.state import Finding, ReasoningState
from cortex.services.llm.grounding import GroundingValidator
from cortex.services.llm.reasoning import _EDGE_RANK, _EDGE_TEMPLATES


def observe(state: ReasoningState, deps) -> ReasoningState:
    """Normalize the trigger: clamp the risk score into [0, 1]."""
    state.risk_score = max(0.0, min(1.0, float(state.risk_score)))
    return state


def retrieve(state: ReasoningState, deps) -> ReasoningState:
    """Gather the k-hop evidence subgraph (unless it was supplied on the state)."""
    if state.evidence is None:
        retrieval = getattr(deps, "retrieval", None)
        if retrieval is None:
            return state.halt("no evidence supplied and no retrieval service configured")
        hops = getattr(deps, "evidence_hops", 3)
        state.evidence = retrieval.gather_evidence(
            org_id=state.org_id, node_id=state.node_id, hops=hops
        )
    if state.evidence is None:
        return state.halt("no evidence for node")
    return state


def verify(state: ReasoningState, deps) -> ReasoningState:
    """Gate: the evidence must have an anchor and something to reason over."""
    ev = state.evidence
    if ev is None or ev.anchor is None:
        state.verified = False
        state.verify_reason = "missing anchor"
        return state
    if not ev.edges and len(ev.nodes) <= 1:
        state.verified = False
        state.verify_reason = "isolated node — nothing to corroborate"
        return state
    state.verified = True
    state.verify_reason = f"{len(ev.nodes)} nodes / {len(ev.edges)} edges"
    return state


def graph_traverse(state: ReasoningState, deps) -> ReasoningState:
    """Walk the evidence subgraph into ranked findings + categorized entities."""
    ev = state.evidence
    nodes = {n.id: n for n in ev.nodes}
    by_label: dict[NodeLabel, list] = {}
    for n in ev.nodes:
        by_label.setdefault(n.label, []).append(n)
    state.incidents = by_label.get(NodeLabel.INCIDENT, [])
    state.services = by_label.get(NodeLabel.SERVICE, [])
    state.owners = by_label.get(NodeLabel.PERSON, [])

    max_clauses = getattr(deps, "max_clauses", 6)
    seen: set[str] = set()
    findings: list[Finding] = []
    for edge in sorted(ev.edges, key=lambda e: _EDGE_RANK.get(e.type, 99)):
        src = nodes.get(edge.from_id)
        dst = nodes.get(edge.to_id)
        template = _EDGE_TEMPLATES.get(edge.type)
        if not src or not dst or not template:
            continue
        phrase = template.format(src=src.display(), dst=dst.display())
        if phrase in seen:
            continue
        seen.add(phrase)
        findings.append(Finding(
            text=phrase, edge_id=edge.id, node_ids=[src.id, dst.id],
            weight=_EDGE_RANK.get(edge.type, 99),
        ))
        if len(findings) >= max_clauses:
            break
    state.findings = findings
    return state


def reason(state: ReasoningState, deps) -> ReasoningState:
    """Compose a summary + base explanation from the findings."""
    anchor = state.evidence.anchor
    state.summary = f"{anchor.display()} is at risk (score {state.risk_score:.2f})."
    parts = [state.summary]
    if state.findings:
        parts.append(" ".join(f"{f.text}." for f in state.findings))
    state.explanation = " ".join(parts)
    return state


def ground(state: ReasoningState, deps) -> ReasoningState:
    """Attach citations for every named entity/relationship, then validate them against the
    evidence and derive confidence from the survivors."""
    ev = state.evidence
    anchor = ev.anchor
    nodes = {n.id: n for n in ev.nodes}
    edges_by_id = {e.id: e for e in ev.edges}

    citations: list[Citation] = [
        Citation(ref_id=anchor.id, kind="node", label=anchor.label.value, confidence=anchor.confidence)
    ]
    cited = {anchor.id}
    for finding in state.findings:
        for nid in finding.node_ids:
            if nid in cited:
                continue
            node = nodes.get(nid)
            if node:
                citations.append(Citation(
                    ref_id=node.id, kind="node", label=node.label.value, confidence=node.confidence
                ))
                cited.add(nid)
        edge = edges_by_id.get(finding.edge_id) if finding.edge_id else None
        if edge:
            citations.append(Citation(
                ref_id=edge.id, kind="edge", label=edge.type.value, confidence=edge.confidence
            ))

    validator = GroundingValidator(ev)
    grounded = validator.filter(citations)
    state.citations = grounded
    state.confidence = validator.confidence(grounded)
    return state


def explain(state: ReasoningState, deps) -> ReasoningState:
    """Turn the base explanation into the final human-readable narrative."""
    text = state.explanation
    if state.incidents:
        severity = state.incidents[0].properties.get("severity", "an open incident")
        text += f" The blocking incident is {severity} and still open."
    state.narrative = text
    state.explanation = text
    return state


def recommend(state: ReasoningState, deps) -> ReasoningState:
    """Derive recommended actions from the findings."""
    actions: list[RecommendedAction] = []
    if state.incidents and state.services:
        actions.append(RecommendedAction(
            title="Hold the deployment until the incident clears",
            detail=f"{state.services[0].display()} is affected by {state.incidents[0].display()}; "
                   "deploying now risks a failed or rolled-back release.",
        ))
    if state.owners:
        actions.append(RecommendedAction(
            title=f"Loop in {state.owners[0].display()}",
            detail=f"{state.owners[0].display()} owns the affected service and is the fastest "
                   "path to resolution.",
        ))
    state.actions = actions
    return state


def notify(state: ReasoningState, deps) -> ReasoningState:
    """Decide whether this interrupts a human and on which channel."""
    interrupt_at = getattr(deps, "interrupt_at", 0.75)
    state.should_notify = state.risk_score >= interrupt_at and state.confidence > 0.0
    state.channel_hint = "slack" if state.should_notify else "digest"
    return state
