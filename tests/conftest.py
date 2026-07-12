"""Pytest fixtures shared across the suite."""

from __future__ import annotations

import pytest

from cortex.tools.synthetic.scenario import ORG_ID, deploy_will_fail_scenario
from cortex.tools.wiring import Pipeline, build_pipeline


@pytest.fixture
def org_id() -> str:
    return ORG_ID


@pytest.fixture
def pipeline() -> Pipeline:
    p = build_pipeline(ORG_ID)
    p.run_scenario(deploy_will_fail_scenario())
    return p
