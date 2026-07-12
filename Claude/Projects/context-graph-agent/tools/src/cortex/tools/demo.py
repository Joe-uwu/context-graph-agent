"""End-to-end demo: run the deploy-will-fail scenario through the whole pipeline and
print the proactive notification the graph produced.

    python -m cortex.tools.demo        (or: cortex-demo)
"""

from __future__ import annotations

from cortex.platform.logging import configure_logging
from cortex.tools.synthetic.scenario import ORG_ID, deploy_will_fail_scenario
from cortex.tools.wiring import build_pipeline


def main() -> None:
    configure_logging(level="WARNING", json_output=False)  # quiet the per-stage logs
    pipeline = build_pipeline(ORG_ID)
    pipeline.run_scenario(deploy_will_fail_scenario())

    nodes = pipeline.repo.all_nodes(org_id=ORG_ID)
    print("\n=== Context graph ===")
    print(f"{len(nodes)} nodes across "
          f"{len({n.source for n in nodes})} sources")

    print("\n=== Top risks ===")
    for node in pipeline.repo.top_by_urgency(org_id=ORG_ID, limit=5, min_score=0.01):
        print(f"  {node.urgency:>5.2f}  {node.label.value:<12} {node.display()}")

    print("\n=== Proactive notifications ===")
    if not pipeline.delivered:
        print("  (none crossed the interrupt bar)")
    for n in pipeline.delivered:
        print(f"\n  [{n.channel.value.upper()}] score={n.risk_score:.2f} "
              f"confidence={n.confidence:.2f} -> {', '.join(n.recipients)}")
        print(f"  {n.title}")
        print(f"  {n.body}")

    if pipeline.bus.dead_letters:
        print(f"\n[!] {len(pipeline.bus.dead_letters)} events dead-lettered")


if __name__ == "__main__":
    main()
