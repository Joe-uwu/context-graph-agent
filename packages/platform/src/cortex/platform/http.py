"""Shared HTTP surface for every service.

Each service is a Kafka consumer AND an HTTP server: the consumer does the pipeline work,
the HTTP server exposes liveness (/health), readiness (/ready), and Prometheus metrics
(/metrics) plus the service's own read/control routes. This module builds that common
surface so a service's own module only declares its domain routes.

`serve()` is the composition root a service's main.py calls: it configures logging and
tracing, starts the consumer on a background thread (kafka runtime), marks the service
ready, and runs uvicorn. The in-memory runtime has no consumer loop, so serve() just runs
the HTTP server over whatever state was wired in.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from cortex.platform.config import ServiceSettings
from cortex.platform.logging import configure_logging, get_logger
from cortex.platform.observability import METRICS, configure_tracing

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import FastAPI

log = get_logger("cortex.http")


def _require_fastapi():
    try:
        import fastapi  # noqa: F401
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "cortex services require the 'api' extra (fastapi, uvicorn)"
        ) from exc


class Readiness:
    """A latch flipped to True once a service has finished start-up (consumer subscribed,
    stores reachable). /health is liveness (the process is up); /ready is readiness (it can
    serve). Kubernetes and compose use them differently, so they are distinct."""

    def __init__(self) -> None:
        self._ready = False
        self._detail = "starting"

    def set_ready(self, detail: str = "ok") -> None:
        self._ready = True
        self._detail = detail

    def set_not_ready(self, detail: str) -> None:
        self._ready = False
        self._detail = detail

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def detail(self) -> str:
        return self._detail


def create_base_app(
    service_name: str,
    *,
    version: str = "0.1.0",
    readiness: Readiness | None = None,
    description: str | None = None,
) -> "FastAPI":
    """Build a FastAPI app pre-wired with health/ready/metrics and request metrics.

    Services call this, then attach their own routes to the returned app.
    """
    _require_fastapi()
    from fastapi import FastAPI, Request, Response
    from fastapi.responses import PlainTextResponse

    readiness = readiness or Readiness()
    readiness_ref = readiness

    app = FastAPI(
        title=f"Cortex {service_name}",
        version=version,
        description=description or f"{service_name} — part of the Cortex context-graph platform.",
    )
    app.state.service_name = service_name
    app.state.readiness = readiness_ref

    # Permissive CORS so the browser dashboard (a static SPA on another origin) can call the
    # API. Services are internal; tighten allow_origins in a hardened deployment.
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_credentials=False,
        allow_methods=["*"], allow_headers=["*"],
    )

    METRICS.register(
        "cortex_http_requests_total", "counter", "HTTP requests handled, by route and status."
    )
    METRICS.register(
        "cortex_http_request_duration_seconds", "histogram", "HTTP request latency in seconds."
    )
    METRICS.register(
        "cortex_http_requests_in_flight", "gauge", "In-flight HTTP requests."
    )

    @app.middleware("http")
    async def _metrics_mw(request: Request, call_next: Callable):  # type: ignore[type-arg]
        METRICS.inc("cortex_http_requests_in_flight", 1.0, service=service_name)
        start = time.perf_counter()
        status = 500
        try:
            response: Response = await call_next(request)
            status = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - start
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            METRICS.inc(
                "cortex_http_requests_total", 1.0,
                service=service_name, method=request.method, path=path, status=str(status),
            )
            METRICS.observe(
                "cortex_http_request_duration_seconds", elapsed,
                service=service_name, method=request.method, path=path,
            )
            METRICS.inc("cortex_http_requests_in_flight", -1.0, service=service_name)

    @app.get("/health", tags=["ops"], summary="Liveness probe")
    def health() -> dict:
        return {"status": "ok", "service": service_name, "version": version}

    from fastapi.responses import JSONResponse

    @app.get("/ready", tags=["ops"], summary="Readiness probe", response_model=None)
    def ready():
        body = {
            "status": "ready" if readiness_ref.ready else "not_ready",
            "detail": readiness_ref.detail,
            "service": service_name,
        }
        return JSONResponse(body, status_code=200 if readiness_ref.ready else 503)

    @app.get("/metrics", response_class=PlainTextResponse, tags=["ops"], summary="Prometheus metrics")
    def metrics() -> str:
        return METRICS.render()

    return app


def start_consumer_thread(bus, group: str) -> threading.Thread | None:
    """Run the bus consumer loop on a daemon thread, if the bus has one (kafka runtime).

    The in-memory bus has no ``run`` loop (it is driven synchronously by the in-process
    runner), so this returns None and the caller just serves HTTP.
    """
    run = getattr(bus, "run", None)
    if run is None:
        return None

    def _loop() -> None:
        try:
            run(group)
        except Exception:  # noqa: BLE001 - a crashed consumer must be visible in logs
            log.exception("consumer loop crashed", extra={"extra_fields": {"group": group}})

    thread = threading.Thread(target=_loop, name=f"{group}-consumer", daemon=True)
    thread.start()
    log.info("consumer thread started", extra={"extra_fields": {"group": group}})
    return thread


def serve(
    app: "FastAPI",
    settings: ServiceSettings,
    *,
    service_name: str,
    bus=None,
    group: str | None = None,
    readiness: Readiness | None = None,
    on_ready: Callable[[], None] | None = None,
) -> None:
    """Composition root for a service process: configure logging/tracing, start the
    consumer, mark ready, and run the HTTP server. Blocks until the process is stopped."""
    configure_logging(settings.log_level, settings.log_json)
    configure_tracing(service_name, settings.otel_endpoint)

    if bus is not None and group is not None:
        start_consumer_thread(bus, group)

    if on_ready is not None:
        on_ready()
    latch = readiness or getattr(app.state, "readiness", None)
    if latch is not None:
        latch.set_ready()

    log.info(
        "service listening",
        extra={"extra_fields": {
            "service": service_name, "host": settings.http_host, "port": settings.http_port,
            "runtime": settings.runtime,
        }},
    )
    import uvicorn

    uvicorn.run(app, host=settings.http_host, port=settings.http_port, log_config=None)
