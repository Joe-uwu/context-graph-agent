# 0010 — GNN urgency scorer

Status: Accepted (implemented)

## Context

The default urgency scorer is a transparent weighted model (see `docs/design/urgency-scoring.md`). It is explainable and needs no training data, but it treats features additively and cannot learn interactions — e.g. that a blocked dependency matters far more when the owner is already overloaded and a deploy is imminent, in a way that is not the sum of the three. The urgency signal is also relational: an incident's severity and a deployment's proximity live on neighbor nodes, not on the anchor being scored.

## Decision

Ship a learned graph neural network scorer as a drop-in alternative behind a config flag (`CORTEX_SCORER_MODEL=gnn`). It is a 2-layer message-passing GNN (GCN-style propagation over the k-hop subgraph with a scalar urgency readout on the anchor node), implemented directly in NumPy — forward pass and backpropagation are hand-derived, so inference needs no deep-learning framework and the trained weights ship as a small `.npz` inside the ranking package (`services/ranking/gnn/`).

Training has two sources behind one trainer:

- Real data: the UCI "Incident Management Process Enriched Event Log" — 24,918 anonymized ServiceNow incidents with real impact/urgency/priority labels. Each incident becomes a small graph (affected service, incident carrying the real impact as severity, reporting user, owning team) and the model learns to predict the incident's real priority. Held-out Pearson correlation between predicted and actual priority is ~0.91.
- Synthetic data: a generator that builds labeled subgraphs from the domain's urgency logic (relational signals plus label noise), so the model is reproducible with no external dataset.

The feature schema (label/source ordering) is versioned and saved with the weights; a schema mismatch on load raises rather than silently mis-scoring. When the flag is off, or weights/NumPy are unavailable, the weighted model runs. Nothing in the pipeline depends on the GNN being present.

## Consequences

The GNN captures relational interactions the additive model misses — message passing lets the anchor aggregate a neighbor's incident severity or a nearby deployment, which the linear per-node model cannot see. Because it is gated and falls back to the weighted model, it adds no operational dependency: the NumPy implementation has no GPU or service requirement, and the weights load in-process. The costs: a learned scorer is less transparent than the weighted baseline (kept as the default and the explainable reference), and the training labels are imbalanced (about 88% of ServiceNow incidents are the middle priority), so ranking correlation is the meaningful metric rather than raw accuracy. Retraining on an org's own outcome labels (pages, rollbacks, missed deadlines) remains the intended path once that history exists; the loader is structured so a new labeled source drops into the same trainer.

## Alternatives considered

PyTorch / PyTorch Geometric with a GraphSAGE model on a GPU worker — rejected for this build: it adds a heavy dependency and a GPU service for a small model, where a from-scratch NumPy GNN trains in seconds on CPU and ships as a 22 KB weights file. A gradient-boosted model on flattened graph features — loses the graph structure the message-passing model exploits; kept as a possible intermediate. Staying weighted-only — acceptable and still the default; this ADR now records the implemented learned scorer, hence Accepted.
