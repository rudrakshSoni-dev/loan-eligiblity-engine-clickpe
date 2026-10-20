"""split-csv → SQS → load-chunk on PostgreSQL 16, with S3 and SQS served by moto.

The real split handler plans the chunks, the messages travel through a moto queue, and the real
load-chunk handler reads its byte ranges from moto S3 and writes to the throwaway database.
Run with a disposable server (see conftest.py). The full-sample test also needs data/users.csv.
"""

import os
import random
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws

from lambdas.load_chunk import handler as load_module
from lambdas.shared.batches import create_batch, upload_key
from lambdas.shared.config import DbConfig, LoadChunkConfig, SplitCsvConfig, WebhookConfig
from lambdas.shared.db import Database
from lambdas.split_csv import handler as split_module

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set")

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "data" / "users.csv"
FIXTURES = REPO / "tests" / "fixtures"
REGION = "ap-southeast-2"
BUCKET = "clickpe-loan-uploads-it"
UNUSED_DB_CONFIG = DbConfig("unused", 5432, "unused", "unused", "unused", ca_bundle=None)


class Pipeline:
    def __init__(
        self, connect_db: Callable[[], Any], monkeypatch: pytest.MonkeyPatch, chunk_rows: int
    ) -> None:
        self.db = connect_db()
        self.s3 = boto3.client("s3", region_name=REGION)
        self.s3.create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION}
        )
        self.sqs = boto3.client("sqs", region_name=REGION)
        self.queue_url = self.sqs.create_queue(QueueName="ingest")["QueueUrl"]
        split_config = SplitCsvConfig(self.queue_url, 20_971_520, chunk_rows)
        split_app = split_module.Runtime(split_config, self.s3, self.sqs)
        load_config = LoadChunkConfig(
            UNUSED_DB_CONFIG, BUCKET, WebhookConfig("http://n8n.invalid/", "s")
        )
        database = Database(UNUSED_DB_CONFIG, lambda _c: connect_db())
        load_app = load_module.Runtime(load_config, database, self.s3)
        monkeypatch.setattr(split_module, "runtime", lambda: split_app)
        monkeypatch.setattr(load_module, "runtime", lambda: load_app)

    def upload(self, data: bytes) -> uuid.UUID:
        batch_id = create_batch(self.db)
        key = upload_key(batch_id)
        etag = self.s3.put_object(Bucket=BUCKET, Key=key, Body=data)["ETag"].strip('"')
        obj: dict[str, Any] = {"key": key, "eTag": etag, "size": len(data)}
        event = {"s3": {"bucket": {"name": BUCKET}, "object": obj}}
        split_module.handler({"Records": [event]}, None)
        return batch_id

    def drain(self, shuffle_seed: int | None = None, duplicate_every: int = 0) -> list[str]:
        """Deliver every queued message to load-chunk, optionally out of order and twice."""
        bodies: list[str] = []
        while batch := self.sqs.receive_message(
            QueueUrl=self.queue_url, MaxNumberOfMessages=10
        ).get("Messages", []):
            bodies.extend(m["Body"] for m in batch)
        if duplicate_every:
            bodies += bodies[::duplicate_every]
        if shuffle_seed is not None:
            random.Random(shuffle_seed).shuffle(bodies)
        records = [{"messageId": f"m{i}", "body": b} for i, b in enumerate(bodies)]
        failures = load_module.handler({"Records": records}, None)["batchItemFailures"]
        assert failures == []
        return bodies

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
def aws_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    with mock_aws():
        yield


@pytest.fixture
def make_pipeline(
    aws_env: None, connect_db: Callable[[], Any], monkeypatch: pytest.MonkeyPatch
) -> Callable[[int], Pipeline]:
    return lambda chunk_rows: Pipeline(connect_db, monkeypatch, chunk_rows)


def test_full_sample_splits_into_two_chunks_and_loads_every_row(
    make_pipeline: Callable[[int], Pipeline],
) -> None:
    if not SAMPLE.exists():
        pytest.skip("data/users.csv is not present")
    pipeline = make_pipeline(5000)
    batch_id = pipeline.upload(SAMPLE.read_bytes())

    assert len(pipeline.drain()) == 2
    assert pipeline.batch(batch_id) == ["processed", 2, 2, 10000, 0, None]
    assert pipeline.scalar("SELECT count(*) FROM users WHERE batch_id = :id", id=batch_id) == 10000


def test_quoted_newlines_crlf_and_bom_load_with_file_line_numbers(
    make_pipeline: Callable[[int], Pipeline],
) -> None:
    pipeline = make_pipeline(1)
    batch_id = pipeline.upload((FIXTURES / "bom_crlf_quoted.csv").read_bytes())

    assert len(pipeline.drain()) == 3
    assert pipeline.batch(batch_id)[:5] == ["processed", 3, 3, 2, 1]
    names = pipeline.db.run("SELECT name FROM users ORDER BY user_id")
    assert [n for (n,) in names] == ["Mehta, Rohan", "Arun Nair"]
    rejects = pipeline.db.run(
        "SELECT line_no, reason FROM rejected_rows WHERE batch_id = :id", id=batch_id
    )
    assert rejects == [[3, "name: contains a control character"]]


def test_out_of_order_and_duplicate_deliveries_complete_exactly_once(
    make_pipeline: Callable[[int], Pipeline],
) -> None:
    pipeline = make_pipeline(3)
    data = (FIXTURES / "malformed_users.csv").read_bytes()
    batch_id = pipeline.upload(data)

    pipeline.drain(shuffle_seed=5, duplicate_every=2)

    status, total, done, rows_ok, rows_rejected, _ = pipeline.batch(batch_id)
    assert (status, total, done) == ("processed", 4, 4)
    assert rows_ok + rows_rejected == len(data.splitlines()) - 1
    assert (
        pipeline.scalar("SELECT count(*) FROM chunk_loads WHERE batch_id = :id", id=batch_id) == 4
    )
    stored = pipeline.db.run("SELECT line_no FROM rejected_rows ORDER BY line_no")
    assert [line for (line,) in stored] == list(range(2, 2 + rows_rejected))


def test_bad_header_fails_the_batch_through_the_queue(
    make_pipeline: Callable[[int], Pipeline],
) -> None:
    pipeline = make_pipeline(5000)
    batch_id = pipeline.upload((FIXTURES / "header_mismatch.csv").read_bytes())

    pipeline.drain()

    status, *_, error = pipeline.batch(batch_id)
    assert status == "failed"
    assert error == "split failed: missing columns: age; repeated columns: email"
