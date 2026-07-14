"""Real-dataset loaders for training the GNN urgency scorer."""

from cortex.services.ranking.gnn.datasets.servicenow import (
    LABEL_MAPS,
    load_incident_event_log,
)

__all__ = ["load_incident_event_log", "LABEL_MAPS"]
