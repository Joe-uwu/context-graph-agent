"""graph-service process entrypoint.

Consumes entities.extracted, resolves + writes the graph (idempotent MERGE, provenance,
temporal edges), and emits graph.changes, on a background consumer thread; serves the
read HTTP surface over the same repository.
"""

from __future__ import annotations

from cortex.platform.http import Readiness, serve
from cortex.platform.runtime import build_bus, build_graph_repo
from cortex.services.graph.config import GROUP, SERVICE_NAME, GraphSettings
from cortex.services.graph.http import create_app
from cortex.services.graph.worker import GraphWorker


def main() -> None:
    settings = GraphSettings()
    bus = build_bus(settings, client_id=GROUP)
    repo = build_graph_repo(settings)
    GraphWorker(bus, repo)
    readiness = Readiness()
    app = create_app(repo, readiness=readiness)
    serve(app, settings, service_name=SERVICE_NAME, bus=bus, group=GROUP, readiness=readiness)


if __name__ == "__main__":
    main()
