"""JSON log lines: standard fields, request id, exceptions, timed stages."""

import json
import logging
import sys

import pytest

from lambdas.shared.logging import JsonFormatter, configure_logging, log_event, timed

LOGGER = logging.getLogger("test_shared_logging")


def formatted(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    formatter = JsonFormatter()
    return [json.loads(formatter.format(record)) for record in caplog.records]


def test_event_fields_become_top_level_json_keys(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER.name)
    log_event(LOGGER, "chunk_loaded", batch_id="b-1", chunk_id=3, count=5000)
    [line] = formatted(caplog)
    assert line == {
        "level": "INFO",
        "logger": LOGGER.name,
        "stage": "chunk_loaded",
        "batch_id": "b-1",
        "chunk_id": 3,
        "count": 5000,
    }


def test_plain_messages_request_id_and_exceptions_are_kept() -> None:
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "plain %s", ("text",), None)
    record.aws_request_id = "req-42"
    try:
        raise ValueError("bad row")
    except ValueError:
        record.exc_info = sys.exc_info()
    line = json.loads(JsonFormatter().format(record))
    assert line["message"] == "plain text"
    assert line["request_id"] == "req-42"
    assert "ValueError: bad row" in line["error"]


def test_timed_logs_duration_and_fields_added_inside(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER.name)
    with timed(LOGGER, "copy", batch_id="b-1") as fields:
        fields["count"] = 7
    [line] = formatted(caplog)
    assert (line["stage"], line["outcome"], line["count"]) == ("copy", "ok", 7)
    assert isinstance(line["duration_ms"], int)


def test_timed_logs_errors_and_reraises(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER.name)
    with pytest.raises(KeyError), timed(LOGGER, "upsert"):
        raise KeyError("x")
    [line] = formatted(caplog)
    assert (line["level"], line["outcome"]) == ("ERROR", "error")


def test_configure_logging_formats_existing_handlers_as_json() -> None:
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        root.handlers = []
        configure_logging("WARNING")
        assert root.level == logging.WARNING
        assert all(isinstance(h.formatter, JsonFormatter) for h in root.handlers)
        assert len(root.handlers) == 1
    finally:
        root.handlers, root.level = saved_handlers, saved_level
