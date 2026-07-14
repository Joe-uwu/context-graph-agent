# GNN urgency scorer

A message-passing GNN (2-layer GCN with a scalar urgency readout) that scores the k-hop
subgraph around a changed node. Forward pass and backprop are implemented directly in NumPy
(`model.py`); no deep-learning framework is required at inference, and the trained weights ship
as `../assets/gnn_urgency.npz`. Selected with `CORTEX_SCORER_MODEL=gnn`; the transparent weighted
heuristic (`scoring.UrgencyScorer`) is the default and the fallback.

## Why a graph model

The urgency signal is relational: an incident's severity and a deployment's proximity sit on
*neighbor* nodes, not on the anchor service. Message passing lets the anchor aggregate them, so
the model captures cross-source risk a per-node feature model cannot.

## Training

The shipped `../assets/gnn_urgency.npz` was trained on the real dataset below (priority label,
24,918 incidents, held-out Pearson ~0.91 between predicted and actual priority).

Two data sources, same trainer (`train.py`):

Real data — the UCI "Incident management process enriched event log" (24,918 real ServiceNow
incidents with real `impact` / `urgency` / `priority` labels;
http://archive.ics.uci.edu/ml/datasets/Incident+management+process+enriched+event+log). Download
`incident_event_log.csv`, then:

```
python -m cortex.services.ranking.gnn.train --source servicenow \
    --csv /path/to/incident_event_log.csv --label-field priority --out ../assets/gnn_urgency.npz
```

The loader (`datasets/servicenow.py`) collapses each incident to its most-updated event row and
builds a graph — Service anchor, Incident (real impact as severity), reporting Person, owning
Team — labeled with the incident's real priority mapped to [0, 1].

Synthetic data — for environments without the CSV, `--source synthetic` generates labeled
subgraphs from the domain's urgency logic (relational signals + label noise) so the model is
reproducible with no external data:

```
python -m cortex.services.ranking.gnn.train --source synthetic --epochs 80
```

The feature schema (label/source order) is versioned and saved with the weights; a schema
mismatch on load raises rather than silently mis-scoring.
