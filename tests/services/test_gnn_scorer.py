"""GNN urgency scorer tests: shipped weights load, message passing ranks relational risk,
deterministic forward pass, config fallback to the heuristic."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from cortex.contracts.enums import EdgeType, NodeLabel, Source
from cortex.graph_sdk.models import Edge, Node
from cortex.services.ranking.gnn import GNNModel, featurize, load_default_gnn_scorer
from cortex.services.ranking.gnn.model import Adam, bce_loss
from cortex.services.ranking.scoring import UrgencyScorer, build_scorer

_now = datetime.now(timezone.utc)


def _node(nid, label, source=Source.GITHUB, **props):
    return Node(id=nid, org_id="t", label=label, natural_key=nid, source=source.value,
                properties=props, confidence=1.0, created_at=_now, updated_at=_now)


def _edge(t, a, b):
    return Edge(id=f"{t.value}:{a}:{b}", org_id="t", type=t, from_id=a, to_id=b,
               confidence=0.9, valid_from=_now)


def _sev1_deploy_case():
    svc = _node("svc", NodeLabel.SERVICE, criticality="tier0")
    inc = _node("inc", NodeLabel.INCIDENT, Source.PAGERDUTY, severity="SEV1")
    dep = _node("dep", NodeLabel.DEPLOYMENT)
    nodes = [svc, inc, dep]
    edges = [_edge(EdgeType.AFFECTS, "inc", "svc"), _edge(EdgeType.DEPLOYS, "dep", "svc")]
    return svc, nodes, edges


def _benign_case():
    svc = _node("svc2", NodeLabel.SERVICE, criticality="tier3")
    pr = _node("pr", NodeLabel.PULL_REQUEST)
    nodes = [svc, pr]
    edges = [_edge(EdgeType.TOUCHES, "pr", "svc2")]
    return svc, nodes, edges


def test_shipped_weights_load():
    scorer = load_default_gnn_scorer()
    assert scorer is not None, "trained gnn_urgency.npz should ship with the package"


def test_gnn_ranks_relational_risk_above_benign():
    scorer = load_default_gnn_scorer()
    hot = scorer.score(*_sev1_deploy_case())
    cold = scorer.score(*_benign_case())
    # The SEV1 severity lives on a NEIGHBOR node; the GNN must message-pass to see it.
    assert hot.score > cold.score
    assert hot.score > 0.6
    assert cold.score < 0.5
    assert hot.node_id == "svc" and "gnn_base" in hot.features


def test_forward_is_deterministic():
    scorer = load_default_gnn_scorer()
    a = scorer.score(*_sev1_deploy_case()).score
    b = scorer.score(*_sev1_deploy_case()).score
    assert a == b


def test_featurize_shapes_and_self_loops():
    svc, nodes, edges = _sev1_deploy_case()
    X, A, ai = featurize(svc, nodes, edges)
    assert X.shape[0] == A.shape[0] == 3
    assert X.shape[1] == 35  # 23 labels + 7 sources + 5 scalars
    assert np.all(np.diag(A) > 0)  # self-loops present after normalization
    assert ai == 0


def test_backprop_reduces_loss_on_a_tiny_batch():
    # sanity: analytic gradients actually descend the BCE loss
    rng = np.random.default_rng(0)
    model = GNNModel(in_dim=35, hidden=8, seed=1)
    opt = Adam(model, lr=0.05)
    svc, nodes, edges = _sev1_deploy_case()
    X, A, ai = featurize(svc, nodes, edges)
    y = np.array([1.0])
    first = bce_loss(model.forward(X, A, [ai], train=True), y)
    for _ in range(50):
        model.forward(X, A, [ai], train=True)
        opt.step(model.backward(y))
    last = bce_loss(model.forward(X, A, [ai]), y)
    assert last < first


def test_build_scorer_falls_back_to_heuristic():
    from types import SimpleNamespace

    assert isinstance(build_scorer(SimpleNamespace(scorer_model="heuristic")), UrgencyScorer)
    # gnn selected + weights present -> GNNScorer (not the heuristic)
    gnn = build_scorer(SimpleNamespace(scorer_model="gnn"))
    assert gnn.__class__.__name__ == "GNNScorer"
