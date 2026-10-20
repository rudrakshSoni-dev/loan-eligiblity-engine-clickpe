"""load-chunk end to end on PostgreSQL 16: the handler, the real schema, an in-memory S3.

Run with a disposable server (see conftest.py). The full-sample test also needs data/users.csv.
"""

import logging
import os
import uuid
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from lambdas.load_chunk import handler as module
from lambdas.shared.batches import create_batch, upload_key
from lambdas.shared.chunks import ChunkMessage, SplitFailure, encode_message
from lambdas.shared.config import DbConfig, LoadChunkConfig, WebhookConfig
from lambdas.shared.db import Database
from lambdas.shared.validation import UserRow, ValidationResult
from tests.chunk_helpers import BUCKET, FakeS3, line_chunks

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set")

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "data" / "users.csv"
FIXTURES = REPO / "tests" / "fixtures"
UNUSED_DB_CONFIG = DbConfig("unused", 5432, "unused", "unused", "unused", ca_bundle=None)
CONFIG = LoadChunkConfig(UNUSED_DB_CONFIG, BUCKET, WebhookConfig("http://n8n.invalid/", "s"))


class Pipeline:
    def __init__(self, connect_db: Callable[[], Any], monkeypatch: pytest.MonkeyPatch) -> None:
        self.db = connect_db()
        self.s3 = FakeS3()
        app = module.Runtime(CONFIG, Database(UNUSED_DB_CONFIG, lambda _c: connect_db()), self.s3)
        monkeypatch.setattr(module, "runtime", lambda: app)

    def upload(self, data: bytes, rows_per_chunk: int) -> list[ChunkMessage]:
        batch_id = create_batch(self.db)
        etag = self.s3.put(upload_key(batch_id), data)
        return line_chunks(data, batch_id, etag, rows_per_chunk)

    def deliver(self, *messages: ChunkMessage | SplitFailure) -> list[dict[str, str]]:
        records = [
            {"messageId": f"m{i}", "body": encode_message(m)} for i, m in enumerate(messages)
        ]
        failures: list[dict[str, str]] = module.handler({"Records": records}, None)[
            "batchItemFailures"
        ]
        return failures

    def batch(self, batch_id: uuid.UUID) -> list[Any]:
        row: list[Any] = self.db.run(
            "SELECT status, total_chunks, chunks_done, rows_ok, rows_rejected, error"
            " FROM upload_batches WHERE id = :id",
            id=batch_id,
        )[0]
        return row

    def scalar(self, sql: str, **params: Any) -> Any:
        return self.db.run(sql, **params)[0][0]


@pytest.fixture
def pipeline(connect_db: Callable[[], Any], monkeypatch: pytest.MonkeyPatch) -> Pipeline:
    return Pipeline(connect_db, monkeypatch)


def loaded_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [
        r.event_fields  # type: ignore[attr-defined]
        for r in caplog.records
        if getattr(r, "event_fields", {}).get("stage") == "chunk_loaded"
    ]


def stages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [getattr(r, "event_fields", {}).get("stage", "") for r in caplog.records]


def test_full_sample_loads_once_and_an_identical_reupload_changes_nothing(
    pipeline: Pipeline, caplog: pytest.LogCaptureFixture
) -> None:
    if not SAMPLE.exists():
        pytest.skip("data/users.csv is not present")
    caplog.set_level(logging.INFO)
    data = SAMPLE.read_bytes()
    first = pipeline.upload(data, rows_per_chunk=5000)

    assert pipeline.deliver(*first) == []
    assert pipeline.deliver(*pipeline.upload(data, rows_per_chunk=5000)) == []

    assert pipeline.batch(first[0].batch_id)[:5] == ["processed", 2, 2, 10000, 0]
    assert pipeline.scalar("SELECT count(*) FROM users") == 10000
    assert (
        pipeline.scalar("SELECT count(*) FROM users WHERE batch_id = :id", id=first[0].batch_id)
        == 10000
    )
    counts = [(e["inserted"], e["updated"], e["unchanged"]) for e in loaded_events(caplog)]
    assert counts == [(5000, 0, 0), (5000, 0, 0), (0, 0, 5000), (0, 0, 5000)]


def test_redelivered_chunk_is_a_no_op(pipeline: Pipeline, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    chunks = pipeline.upload((FIXTURES / "good_users.csv").read_bytes(), rows_per_chunk=2)

    assert pipeline.deliver(chunks[0], chunks[0], *chunks[1:], chunks[0]) == []

    assert pipeline.batch(chunks[0].batch_id)[:5] == ["processed", 3, 3, 5, 0]
    assert pipeline.scalar("SELECT count(*) FROM chunk_loads") == 3
    assert [e["duplicate"] for e in loaded_events(caplog)] == [False, True, False, False]
    assert stages(caplog)[-2:] == ["batch_processed", "chunk_skipped"]
    assert len(pipeline.s3.reads) == 4


def test_malformed_rows_are_reported_with_file_line_numbers_and_good_rows_load(
    pipeline: Pipeline,
) -> None:
    data = (FIXTURES / "malformed_users.csv").read_bytes()
    chunks = pipeline.upload(data, rows_per_chunk=4)
    data_lines = len(data.splitlines()) - 1

    assert pipeline.deliver(*chunks) == []

    status, _, _, rows_ok, rows_rejected, _ = pipeline.batch(chunks[0].batch_id)
    stored = pipeline.db.run("SELECT line_no, reason FROM rejected_rows ORDER BY line_no")
    assert status == "processed"
    assert rows_ok + rows_rejected == data_lines
    assert pipeline.scalar("SELECT count(*) FROM users") == rows_ok
    assert [line for line, _ in stored] == list(range(2, 2 + rows_rejected))
    assert "age: missing" in stored[0][1]


def test_bad_bytes_and_nul_reject_only_their_lines_and_store_readably(pipeline: Pipeline) -> None:
    header = b"user_id,name,email,monthly_income,credit_score,employment_status,age\n"
    rows = [
        b"00000000-0000-4000-8000-000000000101,Ana,ana@example.invalid,30000,700,Salaried,30\n",
        b"00000000-0000-4000-8000-000000000102,R\xe9na,r@example.invalid,30000,700,Salaried,30\n",
        b"00000000-0000-4000-8000-000000000103,N\x00ul,n@example.invalid,30000,700,Salaried,30\n",
    ]
    chunks = pipeline.upload(header + b"".join(rows), rows_per_chunk=10)

    assert pipeline.deliver(*chunks) == []

    stored = pipeline.db.run("SELECT line_no, reason, raw FROM rejected_rows ORDER BY line_no")
    assert pipeline.batch(chunks[0].batch_id)[:5] == ["processed", 1, 1, 1, 2]
    assert [(line, reason) for line, reason, _ in stored] == [
        (3, "not valid UTF-8"),
        (4, "name: contains a control character"),
    ]
    assert stored[0][2].startswith("00000000-0000-4000-8000-000000000102,R�na,")
    assert "N�ul" in stored[1][2]


def test_changed_rows_are_updated_and_move_to_the_new_batch(pipeline: Pipeline) -> None:
    data = (FIXTURES / "good_users.csv").read_bytes()
    first = pipeline.upload(data, rows_per_chunk=10)
    pipeline.deliver(*first)
    changed = data.replace(b",Salaried,", b",Business,", 1)
    second = pipeline.upload(changed, rows_per_chunk=10)

    pipeline.deliver(*second)

    moved = pipeline.scalar(
        "SELECT count(*) FROM users WHERE batch_id = :id", id=second[0].batch_id
    )
    assert moved == 1
    assert pipeline.scalar("SELECT count(*) FROM users") == 5


def test_split_failure_marks_the_batch_failed(pipeline: Pipeline) -> None:
    batch_id = create_batch(pipeline.db)

    assert pipeline.deliver(SplitFailure(batch_id, "missing columns: age")) == []

    assert pipeline.batch(batch_id)[0] == "failed"
    assert pipeline.batch(batch_id)[5] == "split failed: missing columns: age"


def test_replaced_object_fails_the_batch_and_later_chunks_are_skipped(
    pipeline: Pipeline,
) -> None:
    data = (FIXTURES / "good_users.csv").read_bytes()
    chunks = pipeline.upload(data, rows_per_chunk=2)
    pipeline.s3.put(chunks[0].s3_key, data + b"\n")

    assert pipeline.deliver(*chunks) == []

    status, _, chunks_done, rows_ok, _, error = pipeline.batch(chunks[0].batch_id)
    assert (status, chunks_done, rows_ok) == ("failed", 0, 0)
    assert error == "chunk 0: S3 refused chunk 0: PreconditionFailed"
    assert len(pipeline.s3.reads) == 1


def test_data_the_database_refuses_rolls_back_the_chunk_and_fails_the_batch(
    pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunks = pipeline.upload((FIXTURES / "good_users.csv").read_bytes(), rows_per_chunk=10)
    invalid = UserRow(uuid.uuid4(), "X", "x@example.invalid", Decimal(1), 950, "Salaried", 30)
    monkeypatch.setattr(
        module, "validate_chunk", lambda _data, _message: ValidationResult(valid=[invalid])
    )

    assert pipeline.deliver(*chunks) == []

    status, _, chunks_done, *_, error = pipeline.batch(chunks[0].batch_id)
    assert (status, chunks_done) == ("failed", 0)
    assert "23514" in error
    assert pipeline.scalar("SELECT count(*) FROM chunk_loads") == 0
    assert pipeline.scalar("SELECT count(*) FROM users") == 0
