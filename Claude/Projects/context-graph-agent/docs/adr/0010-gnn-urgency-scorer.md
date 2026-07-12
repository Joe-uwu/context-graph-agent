# 0010 — Optional GNN urgency scorer

Status: Proposed

## Context

The default urgency scorer is a transparent weighted model (see `docs/design/urgency-scoring.md`). It is explainable and needs no training data, but it treats features additively and cannot learn interactions — e.g. that a blocked dependency matters far more when the owner is already overloaded and a deploy is imminent, in a way that is not the sum of the three.

## Decision

Allow, but do not require, a learned graph neural network scorer (GraphSAGE-style over the k-hop subgraph) as a drop-in alternative behind a per-org config flag. It trains on outcome labels — did this node lead to a page, a rollback, a missed deadline — collected from the platform's own history. It runs as a Modal GPU worker and returns a score plus node-level attention weights for explainability. When no trained model exists for an org, or the flag is off, the weighted model runs. Nothing in the pipeline depends on the GNN being present.

## Consequences

Where enough labeled history exists, the GNN can capture feature interactions the linear model misses and improve ranking precision. Attention weights preserve some explainability. Because it is optional and gated, it adds no operational dependency to the core system and can be evaluated against the weighted model before being trusted. The costs: it needs labeled outcomes (a cold-start problem for a new org), GPU inference, and ongoing retraining; and a learned scorer is less transparent than the weighted one, which is why the weighted model remains the default and the explainable baseline.

## Alternatives considered

Making the GNN the primary scorer — rejected: it cannot cold-start without labels and sacrifices the explainability that makes notifications trustworthy. A gradient-boosted model on flattened graph features — a reasonable middle option that loses the graph structure the GNN exploits; kept as a possible intermediate. Staying weighted-only forever — acceptable and the current default; this ADR only reserves the option, hence status Proposed rather than Accepted.
