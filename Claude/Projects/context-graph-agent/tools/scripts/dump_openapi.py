#!/usr/bin/env python3
"""Export every service's OpenAPI document to docs/api/openapi/<service>.json.

Each FastAPI app generates its own schema from the typed routes; this builds every service
app (over the in-memory pipeline so no infrastructure is needed) and writes the specs, so
the committed OpenAPI docs never drift from the code.

    python tools/scripts/dump_openapi.py            # writes docs/api/openapi/*.json
    python tools/scripts/dump_openapi.py --check     # fail if the committed specs are stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def build_apps() -> dict:
    from cortex.platform.bus import InMemoryEventBus
    from cortex.services.api.app import create_app as api_app
    from cortex.services.entity.http import create_app as entity_app
    from cortex.services.entity.worker import EntityWorker
    from cortex.services.graph.http import create_app as graph_app
    from cortex.services.ingestion.connectors.mock import MockConnector
    from cortex.services.ingestion.http import create_app as ingestion_app
    from cortex.services.ingestion.worker import IngestionWorker
    from cortex.services.llm.http import create_app as llm_app
    from cortex.services.llm.reasoning import TemplateReasoner
    from cortex.services.notification.http import create_app as notification_app
    from cortex.services.ranking.http import create_app as ranking_app
    from cortex.services.ranking.scoring import UrgencyScorer
    from cortex.services.retrieval.http import create_app as retrieval_app
    from cortex.tools.synthetic.scenario import ORG_ID, deploy_will_fail_scenario
    from cortex.tools.wiring import build_pipeline

    p = build_pipeline(ORG_ID)
    p.run_scenario(deploy_will_fail_scenario())

    ingestion_worker = IngestionWorker(InMemoryEventBus(), ORG_ID)
    ingestion_worker.register(MockConnector("mixed", deploy_will_fail_scenario()))

    return {
        "api-service": api_app(p.repo, p.retrieval, p.notifications),
        "ingestion-service": ingestion_app(ingestion_worker),
        "entity-service": entity_app(EntityWorker(InMemoryEventBus())),
        "graph-service": graph_app(p.repo),
        "retrieval-service": retrieval_app(p.retrieval),
        "ranking-service": ranking_app(p.repo, UrgencyScorer()),
        "llm-service": llm_app(p.retrieval, TemplateReasoner()),
        "notification-service": notification_app(p.notifications),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export service OpenAPI specs.")
    parser.add_argument("--out", default="docs/api/openapi", help="Output directory.")
    parser.add_argument("--check", action="store_true", help="Fail if committed specs are stale.")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []
    for name, app in build_apps().items():
        spec = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
        path = out / f"{name}.json"
        if args.check:
            existing = path.read_text() if path.exists() else ""
            if existing != spec:
                stale.append(name)
        else:
            path.write_text(spec)
            print(f"wrote {path}")

    if args.check and stale:
        print(f"stale OpenAPI specs: {', '.join(stale)} (run dump_openapi.py)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
