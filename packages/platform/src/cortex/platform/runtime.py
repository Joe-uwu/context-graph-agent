"""Runtime selection: build the bus and (optionally) the graph repository from settings.

This is the seam between the in-memory runtime and the production runtime. A service's
main.py asks for a bus/repo and gets the implementation the environment selected, without
knowing which. See CODE_README.md ("Two runtimes, one codebase").
"""

import time

from cortex.platform.bus import EventBus, InMemoryEventBus
from cortex.platform.config import ServiceSettings
from cortex.platform.logging import get_logger

log = get_logger("cortex.runtime")


def build_bus(settings: ServiceSettings, *, client_id: str) -> EventBus:
    if settings.runtime == "kafka":
        from cortex.platform.kafka_bus import KafkaEventBus

        return KafkaEventBus(settings.kafka_bootstrap, client_id=client_id)
    return InMemoryEventBus()


def build_graph_repo(settings: ServiceSettings):
    if settings.runtime == "kafka":
        from cortex.graph_sdk.neo4j_repo import Neo4jGraphRepository

        repo = Neo4jGraphRepository(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
        _wait_for_neo4j(repo, attempts=settings.neo4j_connect_attempts, delay=settings.neo4j_connect_delay)
        return repo
    from cortex.graph_sdk.memory import InMemoryGraphRepository

    return InMemoryGraphRepository()


def _wait_for_neo4j(repo, *, attempts: int, delay: float) -> None:
    """Wait for Neo4j to accept connections, then apply the schema.

    A service can start the moment its Neo4j container is up but before Bolt is query-ready
    (or before auth is initialized). Retrying here means the service does not crash-loop
    during that warmup window; it just waits, then serves.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            repo.verify_connectivity()
            repo.init_schema()
            log.info("neo4j ready", extra={"extra_fields": {"attempt": attempt}})
            return
        except Exception as exc:  # noqa: BLE001 - retry any startup/connectivity error
            last = exc
            log.warning(
                "waiting for neo4j",
                extra={"extra_fields": {"attempt": attempt, "error": str(exc)}},
            )
            time.sleep(delay)
    raise RuntimeError(f"neo4j not ready after {attempts} attempts: {last}")


def run_forever(bus: EventBus, *, group: str) -> None:
    """Block consuming for this service's group (kafka), or return (memory: driven by the
    in-process runner)."""
    run = getattr(bus, "run", None)
    if run is not None:
        run(group)
