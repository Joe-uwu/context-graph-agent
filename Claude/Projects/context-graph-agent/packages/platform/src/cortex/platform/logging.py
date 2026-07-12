"""Structured JSON logging with trace-id correlation.

Log lines carry the trace_id when one is bound, so a line links back to its
distributed trace (see ADR-0009).
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)


def bind_trace_id(trace_id: str | None) -> None:
    _trace_id.set(trace_id)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        tid = _trace_id.get()
        if tid:
            payload["trace_id"] = tid
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
