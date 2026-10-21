"""load-chunk handler outcomes: which messages are acknowledged, retried, or fail their batch."""

import logging
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from pg8000.exceptions import DatabaseError, InterfaceError

from lambdas.load_chunk import handler as module
from lambdas.shared.batches import BatchStateError, upload_key
from lambdas.shared.chunks import (
    ChunkMessage,
    ChunkRejectedError,
    ChunkUnavailableError,
    SplitFailure,
    encode_message,
)
from lambdas.shared.config import ConfigError, DbConfig, LoadChunkConfig, WebhookConfig
from lambdas.shared.db import Database
from lambdas.shared.notify import send_request
from lambdas.shared.validation import REQUIRED_COLUMNS, HeaderError
from tests.chunk_helpers import BUCKET, FakeS3
from tests.webhook_helpers import RecordingSender

BATCH = uuid.UUID("00000000-0000-4000-8000-0000000000cc")
DB_CONFIG = DbConfig("db", 5432, "loans", "user", "pw", ca_bundle=None)
CONFIG = LoadChunkConfig(DB_CONFIG, BUCKET, WebhookConfig("http://n8n:5678/webhook/x", "s"))
CHUNK = ChunkMessage(
    batch_id=BATCH,
    s3_key=upload_key(BATCH),
    etag="e",
    chunk_no=2,
    total_chunks=4,
    start_byte=10,
    end_byte=20,
    first_line_no=2,
    row_count=1,
    columns=REQUIRED_COLUMNS,
)


class FailConnection:
    def __init__(self, fail_with: Exception | None = None) -> None:
        self.fail_with = fail_with
        self.failed: list[dict[str, Any]] = []
        self.closed = False

    def run(self, sql: str, **params: Any) -> list[list[Any]]:
        if sql.startswith("UPDATE upload_batches SET status = 'failed'"):
            if self.fail_with is not None:
                raise self.fail_with
            self.failed.append(params)
            return [[params["id"]]]
        return [[1]]

    def close(self) -> None:
        self.closed = True


def install(
    monkeypatch: pytest.MonkeyPatch,
    load: Callable[[module.Runtime, ChunkMessage], None],
    conn: FailConnection | None = None,
) -> FailConnection:
    conn = conn or FailConnection()
    database = Database(DB_CONFIG, connector=lambda _c: conn)
    app = module.Runtime(CONFIG, database, FakeS3(), RecordingSender())
    monkeypatch.setattr(module, "runtime", lambda: app)
    monkeypatch.setattr(module, "load", load)
    return conn


def event(*bodies: str) -> dict[str, Any]:
    return {"Records": [{"messageId": f"m{i}", "body": b} for i, b in enumerate(bodies)]}


def raising(error: Exception) -> Callable[[module.Runtime, ChunkMessage], None]:
    def load(_app: module.Runtime, _message: ChunkMessage) -> None:
        raise error

    return load


def test_loaded_chunk_is_acknowledged(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: list[ChunkMessage] = []
    conn = install(monkeypatch, lambda _app, message: loaded.append(message))

    assert module.handler(event(encode_message(CHUNK)), None) == {"batchItemFailures": []}
    assert loaded == [CHUNK]
    assert conn.failed == []


def test_unparseable_message_is_retried_towards_the_dlq(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, raising(AssertionError("must not load")))
    result = module.handler(event("{}", encode_message(CHUNK).replace("uploads/", "x/")), None)
    assert result == {"batchItemFailures": [{"itemIdentifier": "m0"}, {"itemIdentifier": "m1"}]}


def test_split_failure_fails_the_batch_and_is_acknowledged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = install(monkeypatch, raising(AssertionError("must not load")))
    failure = SplitFailure(batch_id=BATCH, error="missing columns: age")

    assert module.handler(event(encode_message(failure)), None) == {"batchItemFailures": []}
    assert conn.failed[0]["id"] == BATCH
    assert conn.failed[0]["error"] == "split failed: missing columns: age"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ChunkRejectedError("S3 refused chunk 2: PreconditionFailed"), "PreconditionFailed"),
        (BatchStateError("batch has 3 chunks, message says 4"), "has 3 chunks"),
        (HeaderError("missing columns: age"), "missing columns: age"),
        (
            DatabaseError({"C": "23514", "M": "violates check constraint"}),
            "database refused the data (23514: violates check constraint)",
        ),
        (DatabaseError({"C": "22P02", "M": "invalid input"}), "(22P02: invalid input)"),
    ],
)
def test_permanent_problems_fail_the_batch_and_are_acknowledged(
    monkeypatch: pytest.MonkeyPatch, error: Exception, reason: str
) -> None:
    conn = install(monkeypatch, raising(error))

    assert module.handler(event(encode_message(CHUNK)), None) == {"batchItemFailures": []}
    assert conn.failed[0]["error"].startswith("chunk 2: ")
    assert reason in conn.failed[0]["error"]


@pytest.mark.parametrize(
    "error",
    [
        DatabaseError({"C": "40P01", "M": "deadlock detected"}),
        DatabaseError({"C": "57P01", "M": "terminating connection"}),
        InterfaceError("network error"),
        OSError("timed out"),
        ChunkUnavailableError("S3 error SlowDown"),
    ],
)
def test_transient_problems_are_retried_and_drop_the_connection(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    conn = install(monkeypatch, raising(error))
    module.runtime().database.connection()

    assert module.handler(event(encode_message(CHUNK)), None) == {
        "batchItemFailures": [{"itemIdentifier": "m0"}]
    }
    assert conn.failed == []
    assert conn.closed


def event_received(count: int, body: str) -> dict[str, Any]:
    attributes = {"ApproximateReceiveCount": str(count)}
    record = {"messageId": "m0", "body": body, "attributes": attributes}
    return {"Records": [record]}


def test_last_receive_fails_the_batch_naming_the_chunk_and_still_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = install(monkeypatch, raising(OSError("timed out")))

    result = module.handler(event_received(module.MAX_RECEIVES, encode_message(CHUNK)), None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "m0"}]}
    assert conn.failed[0]["id"] == BATCH
    assert conn.failed[0]["error"] == "chunk 2: gave up after 5 receives (OSError: timed out)"


def test_earlier_receives_do_not_fail_the_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = install(monkeypatch, raising(OSError("timed out")))
    module.handler(event_received(module.MAX_RECEIVES - 1, encode_message(CHUNK)), None)
    assert conn.failed == []


def test_last_receive_survives_a_database_that_cannot_record_the_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FailConnection(fail_with=InterfaceError("network error"))
    install(monkeypatch, raising(OSError("timed out")), conn)

    result = module.handler(event_received(module.MAX_RECEIVES, encode_message(CHUNK)), None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "m0"}]}


def test_failing_to_record_the_failure_retries_the_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FailConnection(fail_with=InterfaceError("network error"))
    install(monkeypatch, raising(ChunkRejectedError("gone")), conn)

    assert module.handler(event(encode_message(CHUNK)), None) == {
        "batchItemFailures": [{"itemIdentifier": "m0"}]
    }


def test_long_failure_reasons_are_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = install(monkeypatch, raising(ChunkRejectedError("x" * 5000)))
    module.handler(event(encode_message(CHUNK)), None)
    assert len(conn.failed[0]["error"]) == module.MAX_ERROR_LENGTH


def test_runtime_fails_loudly_on_missing_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DB_HOST", "UPLOAD_BUCKET", "N8N_WEBHOOK_URL", "N8N_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    module.runtime.cache_clear()
    with pytest.raises(ConfigError, match="DB_HOST is missing"):
        module.runtime()
    module.runtime.cache_clear()


def test_runtime_is_built_once_and_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        "DB_HOST": "db.internal",
        "DB_NAME": "loans",
        "DB_USER": "loans_app",
        "DB_PASSWORD": "pw",
        "UPLOAD_BUCKET": BUCKET,
        "N8N_WEBHOOK_URL": "http://172.31.26.164:5678/webhook/match-batch",
        "N8N_WEBHOOK_SECRET": "example-secret",
        "AWS_REGION": "ap-southeast-2",
        "AWS_ACCESS_KEY_ID": "AKIDEXAMPLE",
        "AWS_SECRET_ACCESS_KEY": "example-secret",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    module.runtime.cache_clear()

    first = module.runtime()

    assert first is module.runtime()
    assert first.config.bucket == BUCKET
    assert first.send is send_request
    module.runtime.cache_clear()


NOTIFY_CONFIG = LoadChunkConfig(
    DB_CONFIG, BUCKET, WebhookConfig("http://n8n:5678/webhook/x", "never-logged-secret")
)


class CompletionConnection:
    def __init__(self, wins: bool) -> None:
        self.wins = wins

    def run(self, sql: str, **params: Any) -> list[list[Any]]:
        assert sql.startswith("UPDATE upload_batches SET status = 'processed'")
        return [[params["id"]]] if self.wins else []


def complete(
    wins: bool, sender: RecordingSender, caplog: pytest.LogCaptureFixture
) -> list[dict[str, Any]]:
    caplog.set_level(logging.INFO)
    app = module.Runtime(NOTIFY_CONFIG, Database(DB_CONFIG), FakeS3(), sender)
    module.complete_batch(app, CompletionConnection(wins), CHUNK)
    return [getattr(r, "event_fields", {}) | {"level": r.levelname} for r in caplog.records]


def test_the_completion_winner_posts_the_batch_to_n8n_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sender = RecordingSender()

    events = complete(True, sender, caplog)

    assert sender.batch_ids() == [str(BATCH)]
    assert [e["stage"] for e in events] == ["batch_processed", "webhook_sent"]
    assert events[1]["status"] == 200
    assert events[1]["attempts"] == 1


def test_a_caller_that_loses_the_completion_posts_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sender = RecordingSender()

    events = complete(False, sender, caplog)

    assert sender.requests == []
    assert [(e["stage"], e["won"]) for e in events] == [("completion_checked", False)]


def test_a_refused_webhook_is_logged_as_an_error_and_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sender = RecordingSender(statuses=[404])

    events = complete(True, sender, caplog)

    assert len(sender.requests) == 1
    assert events[-1]["stage"] == "webhook_failed"
    assert events[-1]["level"] == "ERROR"
    assert events[-1]["status"] == 404
    assert "never-logged-secret" not in str(events)
