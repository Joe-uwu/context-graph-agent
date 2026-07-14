"""ranking-service process entrypoint.

Consumes graph.changes, scores changed subgraphs with the UrgencyScorer, writes urgency
back to the graph, and emits risk.scored for nodes crossing the reason threshold — on a
background consumer thread. Serves on-demand scoring over HTTP.
"""

from __future__ import annotations

from cortex.platform.http import Readiness, serve
from cortex.platform.runtime import build_bus, build_graph_repo
from cortex.services.ranking.config import GROUP, SERVICE_NAME, RankingSettings
from cortex.services.ranking.http import create_app
from cortex.services.ranking.scoring import build_scorer
from cortex.services.ranking.worker import RankingWorker


def main() -> None:
    settings = RankingSettings()
    bus = build_bus(settings, client_id=GROUP)
    repo = build_graph_repo(settings)
    scorer = build_scorer(settings)
    RankingWorker(bus, repo, scorer=scorer, reason_at=settings.reason_at, hops=settings.hops)
    readiness = Readiness()
    app = create_app(repo, scorer, hops=settings.hops, readiness=readiness)
    serve(app, settings, service_name=SERVICE_NAME, bus=bus, group=GROUP, readiness=readiness)


if __name__ == "__main__":
    main()
