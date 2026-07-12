"""Runtime selection: build the bus and (optionally) the graph repository from settings.

This is the seam between the in-memory runtime and the production runtime. A service's
main.py asks for a bus/repo and gets the implementation the environment selected, without
knowing which. See CODE_README.md ("Two runtimes, one codebase").
"""

from __future__ import annotations

from cortex.platform.bus import EventBus, InMemoryEventBus
from cortex.platform.config import ServiceSettings


def build_bus(settings: ServiceSettings, *, client_id: str) -> EventBus:
    if settings.runtime == "kafka":
        from cortex.platform.kafka_bus import KafkaEventBus

        return KafkaEventBus(settings.kafka_bootstrap, client_id=client_id)
    return InMemoryEventBus()


def build_graph_repo(settings: ServiceSettings):
    if settings.runtime == "kafka":
        from cortex.graph_sdk.neo4j_repo import Neo4jGraphRepository

        repo = Neo4jGraphRepository(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
        repo.init_schema()
        return repo
    from cortex.graph_sdk.memory import InMemoryGraphRepository

    return InMemoryGraphRepository()


def run_forever(bus: EventBus, *, group: str) -> None:
    """Block consuming for this service's group (kafka), or return (memory: driven by the
    in-process runner)."""
    run = getattr(bus, "run", None)
    if run is not None:
        run(group)
