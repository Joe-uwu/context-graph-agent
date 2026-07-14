"""Real-dataset path for the GNN scorer: parse the UCI ServiceNow incident event log into
training graphs and train on them. Uses a small real-schema fixture; the full CSV (24,918
incidents) trains the shipped weights via `python -m cortex.services.ranking.gnn.train
--source servicenow --csv <path>`."""

from __future__ import annotations

import os

import numpy as np
import pytest

from cortex.contracts.enums import NodeLabel
from cortex.services.ranking.gnn.datasets import LABEL_MAPS, load_incident_event_log
from cortex.services.ranking.gnn.model import Adam, GNNModel, bce_loss
from cortex.services.ranking.gnn.train import _build_batch, train_from_incident_log

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "servicenow_incidents_sample.csv")


def test_loader_parses_real_labels_and_dedups():
    samples = load_incident_event_log(FIXTURE, label_field="priority")
    # 8 distinct incidents; INC0000008 has priority "?" and is dropped -> 7 usable.
    labels_by_anchor = {a.id: label for a, _n, _e, label in samples}
    assert len(samples) == 7
    # INC0000001 -> priority "1 - Critical" -> 0.95; kept row (sys_mod_count 3) has cmdb_ci "CI 22".
    assert labels_by_anchor["svc:CI 22"] == LABEL_MAPS["priority"][1]
    # INC0000002 -> priority "4 - Low" -> 0.20
    assert labels_by_anchor["svc:CI 40"] == LABEL_MAPS["priority"][4]


def test_graph_structure_from_real_row():
    samples = load_incident_event_log(FIXTURE, label_field="priority")
    anchor, nodes, edges, _label = next(s for s in samples if s[0].id == "svc:CI 22")
    labels = {n.label for n in nodes}
    assert anchor.label == NodeLabel.SERVICE
    assert NodeLabel.INCIDENT in labels and NodeLabel.PERSON in labels and NodeLabel.TEAM in labels
    inc = next(n for n in nodes if n.label == NodeLabel.INCIDENT)
    assert inc.properties["severity"] == "SEV1"  # impact "1 - High" -> SEV1
    assert len(edges) == 3  # AFFECTS + TRIGGERS + OWNS


def test_urgency_label_field():
    samples = load_incident_event_log(FIXTURE, label_field="urgency")
    labels = sorted({round(s[3], 2) for s in samples})
    assert set(labels).issubset(set(LABEL_MAPS["urgency"].values()))


def test_real_graphs_train_and_reduce_loss():
    # The 20-incident guard in train_from_incident_log is bypassed here by training directly on
    # the fixture graphs, proving the real-data graphs actually drive learning.
    samples = load_incident_event_log(FIXTURE, label_field="priority")
    X, A, ai, y = _build_batch(samples)
    model = GNNModel(in_dim=X.shape[1], hidden=16, seed=3)
    opt = Adam(model, lr=0.05)
    first = bce_loss(model.forward(X, A, ai, train=True), y)
    for _ in range(150):
        model.forward(X, A, ai, train=True)
        opt.step(model.backward(y))
    assert bce_loss(model.forward(X, A, ai), y) < first


def test_train_from_incident_log_guards_small_data(tmp_path):
    out = tmp_path / "w.npz"
    with pytest.raises(ValueError, match="usable incidents"):
        train_from_incident_log(FIXTURE, str(out), epochs=2)  # fixture < 20 incidents
