"""Typed, env-driven settings shared by every service.

Each service subclasses ServiceSettings to add its own fields. Values come from the
environment (12-factor); nothing is hardcoded per environment.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CORTEX_", extra="ignore")

    environment: str = "local"
    log_level: str = "INFO"
    log_json: bool = True

    # HTTP surface every service exposes (health / ready / metrics + service routes).
    # In compose/k8s each service runs in its own container, so 8000 is fine everywhere;
    # override with CORTEX_HTTP_PORT to run several services on one host.
    http_host: str = "0.0.0.0"
    http_port: int = 8000

    # Backing services. In local mode the in-memory implementations are used and
    # these are ignored; in production the adapters read them.
    kafka_bootstrap: str = "localhost:9092"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    # How long a graph-backed service waits for Neo4j to become query-ready on start
    # (attempts * delay seconds) before giving up. Covers container warmup in compose/k8s.
    neo4j_connect_attempts: int = 30
    neo4j_connect_delay: float = 2.0
    qdrant_url: str = "http://localhost:6333"
    redis_url: str = "redis://localhost:6379/0"

    # "memory" runs the whole pipeline in-process with no external infra; "kafka"
    # uses the real bus and store adapters.
    runtime: str = "memory"

    otel_endpoint: str | None = None
