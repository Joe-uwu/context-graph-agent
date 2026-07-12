"""OpenTelemetry setup and an in-process Prometheus-compatible metrics registry.

configure_tracing wires the OTLP exporter when an endpoint is set (ADR-0009). The
Metrics registry is a small, thread-safe counter/gauge/histogram store with proper
Prometheus text exposition (TYPE/HELP lines, labels, histogram buckets) that every
service exposes at /metrics. It is intentionally dependency-free so a service can emit
metrics without pulling in the full OTel metrics SDK; in a full OTel deployment the
collector scrapes this endpoint (see infra/monitoring/prometheus).
"""

from __future__ import annotations

from collections import defaultdict
from threading import Lock

# Default latency buckets (seconds), covering sub-millisecond to multi-second requests.
DEFAULT_BUCKETS: tuple[float, ...] = (
    0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
)

LabelKey = tuple[tuple[str, str], ...]


def configure_tracing(service_name: str, endpoint: str | None) -> None:
    """Install an OTLP span exporter for `service_name` when an endpoint is configured.

    A no-op when no endpoint is set or the OTel SDK is not installed, so the same call is
    safe in the in-memory runtime and in tests.
    """
    if not endpoint:
        return
    try:  # pragma: no cover - optional dependency
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
    except ImportError:
        pass


def _key(labels: dict[str, str]) -> LabelKey:
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def _render_labels(key: LabelKey, *, extra: tuple[str, str] | None = None) -> str:
    pairs = list(key)
    if extra is not None:
        pairs = [*pairs, extra]
    if not pairs:
        return ""
    inner = ",".join(f'{name}="{_escape(value)}"' for name, value in pairs)
    return "{" + inner + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class _Histogram:
    __slots__ = ("buckets", "counts", "sum", "count")

    def __init__(self, buckets: tuple[float, ...]) -> None:
        self.buckets = buckets
        self.counts = [0 for _ in buckets]
        self.sum = 0.0
        self.count = 0

    def observe(self, value: float) -> None:
        self.sum += value
        self.count += 1
        for i, bound in enumerate(self.buckets):
            if value <= bound:
                self.counts[i] += 1


class Metrics:
    """Thread-safe counter/gauge/histogram registry with Prometheus text exposition.

    Backwards compatible with the original API: ``inc(name)`` and ``gauge(name, value)``
    with no labels behave exactly as before, and ``render()`` still returns exposition
    text — now with TYPE/HELP lines so Prometheus parses it cleanly.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._help: dict[str, str] = {}
        self._type: dict[str, str] = {}
        self._counters: dict[str, dict[LabelKey, float]] = defaultdict(dict)
        self._gauges: dict[str, dict[LabelKey, float]] = defaultdict(dict)
        self._histograms: dict[str, dict[LabelKey, _Histogram]] = defaultdict(dict)
        self._buckets: dict[str, tuple[float, ...]] = {}

    def register(self, name: str, kind: str, help_text: str = "") -> None:
        with self._lock:
            self._type[name] = kind
            if help_text:
                self._help[name] = help_text

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = _key(labels)
        with self._lock:
            self._type.setdefault(name, "counter")
            bucket = self._counters[name]
            bucket[key] = bucket.get(key, 0.0) + value

    def gauge(self, name: str, value: float, **labels: str) -> None:
        key = _key(labels)
        with self._lock:
            self._type.setdefault(name, "gauge")
            self._gauges[name][key] = value

    def observe(
        self, name: str, value: float, *, buckets: tuple[float, ...] | None = None, **labels: str
    ) -> None:
        key = _key(labels)
        with self._lock:
            self._type.setdefault(name, "histogram")
            series = self._histograms[name]
            hist = series.get(key)
            if hist is None:
                hist = _Histogram(buckets or self._buckets.get(name, DEFAULT_BUCKETS))
                series[key] = hist
            hist.observe(value)

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            names = sorted(
                set(self._counters) | set(self._gauges) | set(self._histograms)
            )
            for name in names:
                kind = self._type.get(name, "untyped")
                if name in self._help:
                    lines.append(f"# HELP {name} {self._help[name]}")
                lines.append(f"# TYPE {name} {kind}")
                for key, val in sorted(self._counters.get(name, {}).items()):
                    lines.append(f"{name}{_render_labels(key)} {_fmt(val)}")
                for key, val in sorted(self._gauges.get(name, {}).items()):
                    lines.append(f"{name}{_render_labels(key)} {_fmt(val)}")
                for key, hist in sorted(self._histograms.get(name, {}).items()):
                    cumulative = 0
                    for bound, count in zip(hist.buckets, hist.counts):
                        cumulative = count
                        le = _fmt(bound)
                        lines.append(
                            f"{name}_bucket{_render_labels(key, extra=('le', le))} {cumulative}"
                        )
                    lines.append(
                        f"{name}_bucket{_render_labels(key, extra=('le', '+Inf'))} {hist.count}"
                    )
                    lines.append(f"{name}_sum{_render_labels(key)} {_fmt(hist.sum)}")
                    lines.append(f"{name}_count{_render_labels(key)} {hist.count}")
        return "\n".join(lines) + "\n"


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return repr(value)


METRICS = Metrics()
