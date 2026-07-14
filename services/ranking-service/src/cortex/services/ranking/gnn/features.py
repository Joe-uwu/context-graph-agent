"""Feature extraction for the GNN urgency scorer.

Turns a k-hop subgraph (anchor + neighbor Nodes + Edges) into a node feature matrix X and a
symmetric, degree-normalized adjacency A (with self-loops) — the standard GCN propagation
operator. Message passing over A lets the anchor aggregate signals that live on its neighbors
(an incident's severity, a service's criticality, a deployment's proximity), which is the whole
point of using a graph model here rather than scoring the anchor's local features alone.

The feature schema (label order, source order) is versioned and saved with the trained weights
so inference matches training exactly.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from cortex.contracts.enums import NodeLabel, Source
from cortex.graph_sdk.models import Edge, Node

FEATURE_VERSION = 1

LABELS: list[str] = [label.value for label in NodeLabel]
SOURCES: list[str] = [source.value for source in Source]
_LABEL_IX = {name: i for i, name in enumerate(LABELS)}
_SOURCE_IX = {name: i for i, name in enumerate(SOURCES)}

# scalar lookups (mirrors the heuristic scorer's tables so the GNN sees the same signal)
_SEVERITY = {"SEV1": 1.0, "SEV2": 0.7, "SEV3": 0.4, "SEV4": 0.2}
_CRITICALITY = {"tier0": 1.0, "tier1": 0.75, "tier2": 0.5, "tier3": 0.25}
_PRIORITY = {"Blocker": 1.0, "Critical": 0.85, "High": 0.7, "Medium": 0.45, "Low": 0.2}

_N_SCALARS = 5  # is_anchor, severity, criticality, priority, degree
FEATURE_DIM = len(LABELS) + len(SOURCES) + _N_SCALARS


def _hours_since(ts: datetime | None) -> float:
    if ts is None:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - ts).total_seconds() / 3600.0, 0.0)


def node_vector(node: Node, *, is_anchor: bool, degree: int) -> np.ndarray:
    v = np.zeros(FEATURE_DIM, dtype=np.float64)
    label = node.label.value if hasattr(node.label, "value") else str(node.label)
    if label in _LABEL_IX:
        v[_LABEL_IX[label]] = 1.0
    src = str(node.source)
    v[len(LABELS) + _SOURCE_IX.get(src, _SOURCE_IX["derived"])] = 1.0

    base = len(LABELS) + len(SOURCES)
    props = node.properties or {}
    v[base + 0] = 1.0 if is_anchor else 0.0
    if label == NodeLabel.INCIDENT.value:
        v[base + 1] = _SEVERITY.get(str(props.get("severity")), 0.3)
    if label == NodeLabel.SERVICE.value:
        v[base + 2] = _CRITICALITY.get(str(props.get("criticality")), 0.5)
    if label in (NodeLabel.TICKET.value, NodeLabel.ISSUE.value):
        v[base + 3] = _PRIORITY.get(str(props.get("priority")), 0.4)
    v[base + 4] = min(degree / 5.0, 1.0)
    return v


def featurize(anchor: Node, nodes: list[Node], edges: list[Edge]) -> tuple[np.ndarray, np.ndarray, int]:
    """Return (X [N,F], A_hat [N,N], anchor_index)."""
    ordered: list[Node] = list(nodes)
    if all(n.id != anchor.id for n in ordered):
        ordered = [anchor, *ordered]
    index = {n.id: i for i, n in enumerate(ordered)}
    n = len(ordered)

    adj = np.zeros((n, n), dtype=np.float64)
    for e in edges:
        i, j = index.get(e.from_id), index.get(e.to_id)
        if i is None or j is None:
            continue
        adj[i, j] = 1.0
        adj[j, i] = 1.0  # undirected propagation
    degrees = adj.sum(axis=1).astype(int)

    X = np.stack([
        node_vector(node, is_anchor=(node.id == anchor.id), degree=int(degrees[i]))
        for i, node in enumerate(ordered)
    ])

    a_hat = _normalize_adj(adj)
    return X, a_hat, index[anchor.id]


def _normalize_adj(adj: np.ndarray) -> np.ndarray:
    """Symmetric normalization of A + I:  D^{-1/2} (A+I) D^{-1/2}."""
    n = adj.shape[0]
    a = adj + np.eye(n)
    deg = a.sum(axis=1)
    d_inv_sqrt = np.where(deg > 0, 1.0 / np.sqrt(deg), 0.0)
    return (a * d_inv_sqrt[:, None]) * d_inv_sqrt[None, :]
