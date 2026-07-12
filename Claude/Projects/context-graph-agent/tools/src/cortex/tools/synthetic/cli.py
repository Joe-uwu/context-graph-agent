"""CLI: print the synthetic scenario as JSON (for inspecting the source events)."""

from __future__ import annotations

import json

from cortex.tools.synthetic.scenario import deploy_will_fail_scenario


def main() -> None:
    events = [e.model_dump(mode="json") for e in deploy_will_fail_scenario()]
    print(json.dumps(events, indent=2, default=str))


if __name__ == "__main__":
    main()
