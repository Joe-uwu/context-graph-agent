"""Synthetic training for the GNN urgency scorer.

Generates labeled k-hop subgraphs and trains the message-passing GNN to predict a teacher
urgency in [0,1]. The teacher signal is deliberately relational — an incident's severity and a
deployment's proximity sit on NEIGHBOR nodes, not the anchor — so a bag-of-anchor-features model
cannot fit it and the GNN must aggregate over the graph. Label noise makes it a genuine
regression rather than a lookup. Deterministic under a fixed seed so the shipped weights are
reproducible.

Run:  python -m cortex.services.ranking.gnn.train --epochs 80 --out <path>
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import numpy as np

from cortex.contracts.enums import EdgeType, NodeLabel, Source
from cortex.graph_sdk.models import Edge, Node
from cortex.services.ranking.gnn.features import FEATURE_DIM, featurize
from cortex.services.ranking.gnn.model import Adam, GNNModel, bce_loss

_SEV = {"SEV1": 1.0, "SEV2": 0.7, "SEV3": 0.4, "SEV4": 0.2}
_CRIT = {"tier0": 1.0, "tier1": 0.75, "tier2": 0.5, "tier3": 0.25}
_now = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _node(nid: str, label: NodeLabel, source: Source, **props) -> Node:
    return Node(id=nid, org_id="train", label=label, natural_key=nid, source=source.value,
                properties=props, confidence=1.0, created_at=_now, updated_at=_now)


def _edge(t: EdgeType, a: str, b: str) -> Edge:
    return Edge(id=f"{t.value}:{a}:{b}", org_id="train", type=t, from_id=a, to_id=b,
                confidence=1.0, valid_from=_now)


def _make_graph(rng: np.random.Generator):
    """Build one random subgraph anchored on a service; return (anchor, nodes, edges, label)."""
    crit = rng.choice(list(_CRIT), p=[0.15, 0.25, 0.4, 0.2])
    anchor = _node("svc", NodeLabel.SERVICE, Source.GITHUB, criticality=crit)
    nodes = [anchor]
    edges: list[Edge] = []
    sources = {Source.GITHUB.value}

    n_incidents = rng.choice([0, 1, 2], p=[0.45, 0.4, 0.15])
    sev_score = 0.0
    for i in range(n_incidents):
        sev = rng.choice(list(_SEV), p=[0.2, 0.3, 0.3, 0.2])
        inc = _node(f"inc{i}", NodeLabel.INCIDENT, Source.PAGERDUTY, severity=sev)
        nodes.append(inc)
        edges.append(_edge(EdgeType.AFFECTS, inc.id, anchor.id))
        sources.add(Source.PAGERDUTY.value)
        sev_score = max(sev_score, _SEV[sev])

    has_deploy = rng.random() < 0.4
    if has_deploy:
        dep = _node("dep", NodeLabel.DEPLOYMENT, Source.GITHUB)
        nodes.append(dep)
        edges.append(_edge(EdgeType.DEPLOYS, dep.id, anchor.id))

    n_blocks = rng.choice([0, 1, 2, 3], p=[0.5, 0.25, 0.15, 0.1])
    for j in range(n_blocks):
        dep = _node(f"dpn{j}", NodeLabel.DEPENDENCY, Source.GITHUB)
        nodes.append(dep)
        edges.append(_edge(EdgeType.BLOCKS, dep.id, anchor.id))

    # noise nodes with no urgency bearing (people, PRs, discussion)
    for k in range(rng.integers(0, 4)):
        pr = _node(f"pr{k}", NodeLabel.PULL_REQUEST, Source.GITHUB)
        nodes.append(pr)
        edges.append(_edge(EdgeType.TOUCHES, pr.id, anchor.id))
    if rng.random() < 0.3:
        th = _node("thread", NodeLabel.SLACK_THREAD, Source.SLACK, message_count=int(rng.integers(1, 30)))
        nodes.append(th)
        edges.append(_edge(EdgeType.DISCUSSES, th.id, anchor.id))
        sources.add(Source.SLACK.value)

    # Teacher urgency: relational combination (neighbor-borne signals) + noise.
    corroboration = min(len(sources) / 4.0, 1.0)
    raw = (0.95 * sev_score
           + 0.55 * _CRIT[crit]
           + 0.80 * (1.0 if has_deploy and sev_score > 0 else 0.0)
           + 0.30 * min(n_blocks / 3.0, 1.0)
           + 0.25 * corroboration)
    raw /= (0.95 + 0.55 + 0.80 + 0.30 + 0.25)
    label = 1.0 / (1.0 + np.exp(-7.0 * (raw - 0.42)))
    label = float(np.clip(label + rng.normal(0, 0.05), 0.0, 1.0))
    return anchor, nodes, edges, label


def _build_batch(samples):
    """Block-diagonal batch: stack graphs into one big X and A with anchor indices."""
    blocks_X, blocks_A, anchors, labels, offset = [], [], [], [], 0
    for anchor, nodes, edges, label in samples:
        X, A, ai = featurize(anchor, nodes, edges)
        blocks_X.append(X)
        blocks_A.append(A)
        anchors.append(offset + ai)
        labels.append(label)
        offset += X.shape[0]
    n = offset
    bigA = np.zeros((n, n))
    pos = 0
    for A in blocks_A:
        s = A.shape[0]
        bigA[pos:pos + s, pos:pos + s] = A
        pos += s
    return np.vstack(blocks_X), bigA, np.array(anchors), np.array(labels)


def _featurize_samples(samples):
    """Featurize each graph once (the Python-heavy step) so epochs reuse cached arrays."""
    out = []
    for anchor, nodes, edges, label in samples:
        X, A, ai = featurize(anchor, nodes, edges)
        out.append((X, A, ai, float(label)))
    return out


def _batch_from_cached(cached):
    """Assemble a block-diagonal batch from pre-featurized (X, A, anchor_idx, label) tuples."""
    blocks_X, blocks_A, anchors, labels, offset = [], [], [], [], 0
    for X, A, ai, label in cached:
        blocks_X.append(X)
        blocks_A.append(A)
        anchors.append(offset + ai)
        labels.append(label)
        offset += X.shape[0]
    bigA = np.zeros((offset, offset))
    pos = 0
    for A in blocks_A:
        s = A.shape[0]
        bigA[pos:pos + s, pos:pos + s] = A
        pos += s
    return np.vstack(blocks_X), bigA, np.array(anchors), np.array(labels)


def _fit(cached, *, epochs, batch, lr, seed):
    """Train the GNN over pre-featurized samples; return (model, val_metrics)."""
    rng = np.random.default_rng(seed)
    idx = np.arange(len(cached))
    rng.shuffle(idx)
    split = int(0.9 * len(cached))
    train_ix, val_ix = idx[:split], idx[split:]
    vX, vA, vi, vy = _batch_from_cached([cached[i] for i in val_ix])

    model = GNNModel(in_dim=FEATURE_DIM, hidden=32, seed=seed)
    opt = Adam(model, lr=lr)
    for _ in range(epochs):
        rng.shuffle(train_ix)
        for b in range(0, len(train_ix), batch):
            chunk = [cached[i] for i in train_ix[b:b + batch]]
            X, A, ai, y = _batch_from_cached(chunk)
            model.forward(X, A, ai, train=True)
            opt.step(model.backward(y))
    pv = model.forward(vX, vA, vi)
    corr = float(np.corrcoef(pv, vy)[0, 1]) if len(set(vy.tolist())) > 1 else float("nan")
    return model, {"final_val_loss": bce_loss(pv, vy), "val_pearson": corr}


def train_and_save(out_path: str, *, n_graphs: int = 4000, epochs: int = 80,
                   batch: int = 128, lr: float = 0.01, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    cached = _featurize_samples([_make_graph(rng) for _ in range(n_graphs)])
    model, val = _fit(cached, epochs=epochs, batch=batch, lr=lr, seed=seed)
    model.save(out_path)
    return {"source": "synthetic", "n_graphs": n_graphs, "epochs": epochs, **val}


def train_from_incident_log(csv_path: str, out_path: str, *, label_field: str = "priority",
                           epochs: int = 80, batch: int = 128, lr: float = 0.01,
                           seed: int = 7, limit: int | None = None) -> dict:
    """Train on the real UCI ServiceNow incident event log instead of synthetic graphs."""
    from cortex.services.ranking.gnn.datasets import load_incident_event_log

    data = load_incident_event_log(csv_path, label_field=label_field, limit=limit)
    if len(data) < 20:
        raise ValueError(f"only {len(data)} usable incidents parsed from {csv_path}")
    cached = _featurize_samples(data)
    model, val = _fit(cached, epochs=epochs, batch=batch, lr=lr, seed=seed)
    model.save(out_path)
    return {"source": "servicenow", "label_field": label_field, "incidents": len(data),
            "epochs": epochs, **val}


def main() -> None:
    import os

    ap = argparse.ArgumentParser()
    default_out = os.path.join(os.path.dirname(__file__), "..", "assets", "gnn_urgency.npz")
    ap.add_argument("--out", default=os.path.abspath(default_out))
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--graphs", type=int, default=4000)
    ap.add_argument("--source", choices=["synthetic", "servicenow"], default="synthetic")
    ap.add_argument("--csv", help="path to the UCI incident_event_log.csv (for --source servicenow)")
    ap.add_argument("--label-field", default="priority", choices=["priority", "urgency", "impact"])
    args = ap.parse_args()
    if args.source == "servicenow":
        if not args.csv:
            ap.error("--source servicenow requires --csv PATH")
        metrics = train_from_incident_log(args.csv, args.out, label_field=args.label_field,
                                          epochs=args.epochs)
    else:
        metrics = train_and_save(args.out, n_graphs=args.graphs, epochs=args.epochs)
    print("trained GNN urgency scorer ->", args.out)
    for k, v in metrics.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
