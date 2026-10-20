"""JSON-structured log lines, one object per line, so CloudWatch Logs Insights can query fields.

Standard fields: stage, batch_id, chunk_id, count, duration_ms (plus any extra keyword).
The Lambda runtime installs its own handler on the root logger; `configure_logging` keeps that
handler (it adds the request id) and only swaps its formatter.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

EVENT_ATTR = "event_fields"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            **getattr(record, EVENT_ATTR, {"message": record.getMessage()}),
        }
        request_id = getattr(record, "aws_request_id", None)
        if request_id:
            line["request_id"] = request_id
        if record.exc_info:
            line["error"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    for handler in root.handlers:
        handler.setFormatter(JsonFormatter())


def emit(logger: logging.Logger, level: int, stage: str, fields: Mapping[str, object]) -> None:
    logger.log(level, stage, extra={EVENT_ATTR: {"stage": stage, **fields}})


def log_event(
    logger: logging.Logger, stage: str, *, level: int = logging.INFO, **fields: object
) -> None:
    emit(logger, level, stage, fields)


@contextmanager
def timed(logger: logging.Logger, stage: str, **fields: object) -> Iterator[dict[str, object]]:
    """Log `stage` with duration_ms when the block ends; the block may add fields to the dict.

    A block that raises is logged at ERROR with outcome="error" before the exception propagates.
    """
    extra: dict[str, object] = dict(fields)
    started = time.monotonic()
    try:
        yield extra
    except BaseException:
        elapsed = round((time.monotonic() - started) * 1000)
        emit(logger, logging.ERROR, stage, {"outcome": "error", "duration_ms": elapsed, **extra})
        raise
    elapsed = round((time.monotonic() - started) * 1000)
    emit(logger, logging.INFO, stage, {"outcome": "ok", "duration_ms": elapsed, **extra})
