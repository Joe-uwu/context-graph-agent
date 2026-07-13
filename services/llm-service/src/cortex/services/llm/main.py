"""llm-service process entrypoint.

Consumes risk.scored, gathers evidence, runs the grounded reasoner, and emits
reasoning.produced on a background consumer thread; serves on-demand reasoning over HTTP.
"""

from __future__ import annotations

from cortex.platform.http import Readiness, serve
from cortex.platform.runtime import build_bus, build_graph_repo
from cortex.services.llm.config import GROUP, SERVICE_NAME, LlmSettings
from cortex.services.llm.graph import GraphReasoner, ReasoningConfig
from cortex.services.llm.http import create_app
from cortex.services.llm.worker import LlmWorker
from cortex.services.retrieval.service import RetrievalService


def main() -> None:
    settings = LlmSettings()
    bus = build_bus(settings, client_id=GROUP)
    repo = build_graph_repo(settings)
    retrieval = RetrievalService(repo)
    reasoner = GraphReasoner(
        ReasoningConfig(retrieval=retrieval, evidence_hops=settings.evidence_hops)
    )
    LlmWorker(bus, retrieval, reasoner=reasoner, evidence_hops=settings.evidence_hops)
    readiness = Readiness()
    app = create_app(retrieval, reasoner, evidence_hops=settings.evidence_hops, readiness=readiness)
    serve(app, settings, service_name=SERVICE_NAME, bus=bus, group=GROUP, readiness=readiness)


if __name__ == "__main__":
    main()
