# 0001 — Record architecture decisions

Status: Accepted

## Context

This system makes a number of non-obvious choices (graph over RAG, event-driven over request/response, single-writer stores). Without a record of why, future contributors will either relitigate settled questions or undo a decision without seeing its reasons.

## Decision

Keep an ADR per significant decision in `docs/adr/`, numbered, immutable once accepted, using the Context/Decision/Consequences/Alternatives structure. Superseding a decision means writing a new ADR that references the old one, not editing history.

## Consequences

New engineers can read the ADR log and understand the shape of the system in an hour. Reversals are visible and deliberate. The cost is discipline: a decision worth making is worth a short record.

## Alternatives considered

A single design doc that is edited over time — rejected because it loses the history of why a choice was made and later changed. Wiki pages — rejected because they drift from the code and are not reviewed alongside it; ADRs live in the repo and go through PR review.
