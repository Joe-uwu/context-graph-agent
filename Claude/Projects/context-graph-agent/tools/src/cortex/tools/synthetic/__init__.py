"""Synthetic, cross-source-consistent event generation.

The generator emits the same entities referenced across GitHub, Jira, PagerDuty, Slack,
and Calendar so the graph joins them the way it would with real data — no credentials
required (ADR-0003).
"""

from cortex.tools.synthetic.scenario import deploy_will_fail_scenario

__all__ = ["deploy_will_fail_scenario"]
