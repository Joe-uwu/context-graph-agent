"""ASGI entrypoint for local runs.

Builds the in-memory pipeline, seeds it with the synthetic scenario, and serves the API
over that live state so the dashboard has data without any external infrastructure:

    uvicorn cortex.services.api.server:app --reload

In production this module is replaced by one that wires the real store adapters and the
Kafka consumer group; the route layer (app.py) is unchanged.
"""

from __future__ import annotations

from cortex.platform.http import Readiness
from cortex.services.api.app import create_app
from cortex.tools.synthetic.scenario import ORG_ID, deploy_will_fail_scenario
from cortex.tools.wiring import build_pipeline

_pipeline = build_pipeline(ORG_ID)
_pipeline.run_scenario(deploy_will_fail_scenario())

_readiness = Readiness()
app = create_app(_pipeline.repo, _pipeline.retrieval, _pipeline.notifications, readiness=_readiness)
# The pipeline is seeded and served synchronously, so the gateway is ready at import time.
_readiness.set_ready()
