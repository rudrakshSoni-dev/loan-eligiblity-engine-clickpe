"""Exactly one n8n POST per batch when load-chunk invocations finish chunks at the same time.

Each worker thread plays one warm Lambda instance: its own Runtime and database connection,
calling the real handler. Every chunk is delivered twice and all deliveries of a batch start
together behind a barrier. The webhook is a real local HTTP server, so the POST goes through
urllib exactly as in the Lambda. Run with a disposable server (see conftest.py).
"""

import logging
import os
import threading
import uuid
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from lambdas.load_chunk import handler as module
from lambdas.shared.batches import create_batch, upload_key
from lambdas.shared.chunks import ChunkMessage, encode_message
from lambdas.shared.config import DbConfig, LoadChunkConfig, WebhookConfig
from lambdas.shared.db import Database
from lambdas.shared.notify import AUTH_HEADER, send_request
from tests.chunk_helpers import BUCKET, FakeS3, line_chunks
from tests.webhook_helpers import token_claims, webhook_receiver

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set")

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "good_users.csv"
UNUSED_DB_CONFIG = DbConfig("unused", 5432, "unused", "unused", "unused", ca_bundle=None)
SECRET = "example-signing-key-0123456789abcdef"
RACE_TRIALS = 10
DELIVERIES_PER_CHUNK = 2
BARRIER_TIMEOUT_SECONDS = 30


class Instances:
    """One Runtime per worker thread, like warm Lambda instances that each hold a connection."""

    def __init__(self, connect_db: Callable[[], Any], s3: FakeS3, webhook_url: str) -> None:
        self.config = LoadChunkConfig(UNUSED_DB_CONFIG, BUCKET, WebhookConfig(webhook_url, SECRET))
        self.connect_db = connect_db
        self.s3 = s3
        self.local = threading.local()

    def runtime(self) -> module.Runtime:
        if not hasattr(self.local, "app"):
            database = Database(UNUSED_DB_CONFIG, lambda _c: self.connect_db())
            self.local.app = module.Runtime(self.config, database, self.s3, send_request)
        app: module.Runtime = self.local.app
        return app


def deliver_together(pool: ThreadPoolExecutor, messages: list[ChunkMessage]) -> list[Any]:
    barrier = threading.Barrier(len(messages))

    def deliver(message: ChunkMessage) -> Any:
        barrier.wait(BARRIER_TIMEOUT_SECONDS)
        record = {"messageId": "m0", "body": encode_message(message)}
        return module.handler({"Records": [record]}, None)

    return list(pool.map(deliver, messages))


def stage_counts(caplog: pytest.LogCaptureFixture, stage: str) -> Counter[str]:
    fields = [getattr(r, "event_fields", {}) for r in caplog.records]
    return Counter(f["batch_id"] for f in fields if f.get("stage") == stage)


def test_concurrent_and_duplicate_finishers_post_to_n8n_exactly_once_per_batch(
    connect_db: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    db = connect_db()
    s3 = FakeS3()
    data = FIXTURE.read_bytes()
    batches: list[uuid.UUID] = []
    with webhook_receiver() as n8n:
        instances = Instances(connect_db, s3, n8n.url)
        monkeypatch.setattr(module, "runtime", instances.runtime)
        chunk_count = len(data.splitlines()) - 1
        with ThreadPoolExecutor(chunk_count * DELIVERIES_PER_CHUNK) as pool:
            for _ in range(RACE_TRIALS):
                batch_id = create_batch(db)
                chunks = line_chunks(data, batch_id, s3.put(upload_key(batch_id), data), 1)
                results = deliver_together(pool, chunks * DELIVERIES_PER_CHUNK)
                assert results == [{"batchItemFailures": []}] * len(results)
                batches.append(batch_id)

    statuses = db.run(
        "SELECT status, chunks_done, rows_ok FROM upload_batches"
        " WHERE id = ANY(CAST(:ids AS uuid[]))",
        ids=[str(b) for b in batches],
    )
    assert statuses == [["processed", chunk_count, chunk_count]] * RACE_TRIALS
    assert Counter(n8n.batch_ids()) == Counter({str(b): 1 for b in batches})
    assert [token_claims(r.headers[AUTH_HEADER], SECRET)["batch_id"] for r in n8n.received] == (
        n8n.batch_ids()
    )
    assert stage_counts(caplog, "batch_processed") == Counter({str(b): 1 for b in batches})
    assert stage_counts(caplog, "webhook_sent") == Counter({str(b): 1 for b in batches})
    assert sum(stage_counts(caplog, "completion_checked").values()) >= RACE_TRIALS
