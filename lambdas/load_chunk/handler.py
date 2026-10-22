"""SQS handler: load one chunk of an uploaded CSV into users, then check whether its batch is done.

Runs inside the VPC because it writes to RDS. S3 is read through the Gateway Endpoint and the
Lambda service delivers the SQS messages, so no other AWS API is called. Per message:
    start_loading → ranged S3 read + validation → one transaction (claim chunk, COPY, upsert,
    rejects, finish chunk) → completion check after the commit → POST to n8n by the one winner.

A message is acknowledged when its chunk loaded, was a duplicate delivery, belongs to a batch that
is no longer loading, or can never load (control message, broken split, data the database
refuses); in the last case the batch is marked failed. Database, network and S3 trouble is
returned in `batchItemFailures`, so SQS retries only that message and moves it to ingest-dlq after
5 receives; on the fifth receive the batch is marked failed with the chunk number first. A failed
n8n POST is logged and the message still acknowledged: a redelivery could not
win the completion again, so retrying it would never re-send. Configuration is read on the first
invocation, not at import.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from functools import cache
from typing import Any

from pg8000.exceptions import DatabaseError, InterfaceError

from lambdas.shared.batches import (
    BatchStateError,
    claim_chunk,
    fail_batch,
    finish_chunk,
    start_loading,
    try_complete,
)
from lambdas.shared.chunks import (
    ChunkMessage,
    ChunkRejectedError,
    ChunkUnavailableError,
    MessageError,
    S3RangeReader,
    SplitFailure,
    new_s3_reader,
    parse_message,
    read_chunk,
)
from lambdas.shared.config import LoadChunkConfig, load_chunk_config, log_level
from lambdas.shared.db import Connection, Database, server_error, transaction
from lambdas.shared.loading import store_rejects, upsert_users, validate_chunk
from lambdas.shared.logging import configure_logging, log_event, timed
from lambdas.shared.notify import Sender, notify_batch_processed, send_request
from lambdas.shared.validation import HeaderError, ValidationResult

logger = logging.getLogger("load_chunk")

PERMANENT_SQLSTATE_CLASSES = frozenset({"22", "23"})
RETRYABLE_ERRORS = (DatabaseError, InterfaceError, OSError, ChunkUnavailableError)
MAX_ERROR_LENGTH = 1000
MAX_RECEIVES = 5


@dataclass(frozen=True)
class Runtime:
    """Objects built once per warm container: config, database, S3 reader, sender."""

    config: LoadChunkConfig
    database: Database
    s3: S3RangeReader
    send: Sender


@cache
def runtime() -> Runtime:
    """Configure logging and build the Runtime on the first invocation."""
    configure_logging(log_level(os.environ))
    config = load_chunk_config(os.environ)
    return Runtime(
        config=config,
        database=Database(config.db),
        s3=new_s3_reader(os.environ["AWS_REGION"]),
        send=send_request,
    )


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Process each SQS record and return the ones to retry as `batchItemFailures`."""
    app = runtime()
    retry = [r["messageId"] for r in event.get("Records", []) if not handle_record(app, r)]
    return {"batchItemFailures": [{"itemIdentifier": message_id} for message_id in retry]}


def handle_record(app: Runtime, record: dict[str, Any]) -> bool:
    """Return True to acknowledge the message, False to have SQS deliver it again."""
    try:
        message = parse_message(record.get("body", ""))
    except MessageError as error:
        log_event(
            logger,
            "message_invalid",
            level=logging.ERROR,
            message_id=record.get("messageId"),
            error=str(error),
        )
        return False
    try:
        problem = process(app, message)
        if problem is not None:
            mark_failed(app, message.batch_id, problem)
    except RETRYABLE_ERRORS as error:
        app.database.reset()
        log_event(
            logger,
            "chunk_retry",
            level=logging.WARNING,
            batch_id=str(message.batch_id),
            error=f"{type(error).__name__}: {error}",
        )
        if receive_count(record) >= MAX_RECEIVES:
            give_up(app, message, f"{type(error).__name__}: {error}")
        return False
    return True


def receive_count(record: dict[str, Any]) -> int:
    """Return how many times SQS has delivered this message."""
    return int(record.get("attributes", {}).get("ApproximateReceiveCount", 1))


def give_up(app: Runtime, message: ChunkMessage | SplitFailure, cause: str) -> None:
    """Fail the batch on the last receive, naming the chunk; the message then moves to the DLQ."""
    chunk = getattr(message, "chunk_no", "control")
    reason = f"chunk {chunk}: gave up after {MAX_RECEIVES} receives ({cause})"
    try:
        mark_failed(app, message.batch_id, reason)
    except RETRYABLE_ERRORS as error:
        app.database.reset()
        log_event(
            logger,
            "give_up_unrecorded",
            level=logging.ERROR,
            batch_id=str(message.batch_id),
            error=f"{type(error).__name__}: {error}",
        )


def process(app: Runtime, message: ChunkMessage | SplitFailure) -> str | None:
    """Load the chunk; return why the batch must fail, or None. Retryable errors propagate."""
    if isinstance(message, SplitFailure):
        return f"split failed: {message.error}"
    try:
        load(app, message)
    except (ChunkRejectedError, BatchStateError, HeaderError) as error:
        return f"chunk {message.chunk_no}: {error}"
    except DatabaseError as error:
        code, text = server_error(error)
        if code[:2] not in PERMANENT_SQLSTATE_CLASSES:
            raise
        return f"chunk {message.chunk_no}: database refused the data ({code}: {text})"
    return None


def load(app: Runtime, message: ChunkMessage) -> None:
    """Read, validate and load one chunk, then run the completion check."""
    conn = app.database.connection()
    ids: dict[str, object] = {"batch_id": str(message.batch_id), "chunk_id": message.chunk_no}
    if not start_loading(conn, message.batch_id, message.total_chunks):
        log_event(logger, "chunk_skipped", level=logging.INFO, reason="not loading", **ids)
        return
    result = validate_chunk(read_chunk(app.s3, app.config.bucket, message), message)
    records = len(result.valid) + len(result.rejects)
    if records != message.row_count:
        mismatch = {**ids, "expected": message.row_count, "count": records}
        log_event(logger, "row_count_mismatch", level=logging.WARNING, **mismatch)
    with timed(logger, "chunk_loaded", **ids) as fields:
        fields.update(load_in_transaction(conn, message, result))
    complete_batch(app, conn, message)


def complete_batch(app: Runtime, conn: Connection, message: ChunkMessage) -> None:
    """Finish the batch if every chunk is in; only the one caller that wins announces it to n8n."""
    batch_id, chunk_id = str(message.batch_id), message.chunk_no
    if not try_complete(conn, message.batch_id):
        log_event(logger, "completion_checked", won=False, batch_id=batch_id, chunk_id=chunk_id)
        return
    log_event(logger, "batch_processed", batch_id=batch_id, chunk_id=chunk_id)
    result = notify_batch_processed(app.config.webhook, message.batch_id, app.send)
    log_event(
        logger,
        "webhook_sent" if result.delivered else "webhook_failed",
        level=logging.INFO if result.delivered else logging.ERROR,
        batch_id=batch_id,
        chunk_id=chunk_id,
        attempts=result.attempts,
        status=result.status,
        error=result.error,
    )


def load_in_transaction(
    conn: Connection, message: ChunkMessage, result: ValidationResult
) -> dict[str, object]:
    """Claim, load and record the chunk in one transaction; a duplicate delivery changes nothing."""
    with transaction(conn):
        if not claim_chunk(conn, message.batch_id, message.chunk_no):
            return {"duplicate": True}
        counts = upsert_users(conn, message.batch_id, result.valid)
        stored = store_rejects(conn, message.batch_id, result.rejects)
        finish_chunk(
            conn, message.batch_id, message.chunk_no, len(result.valid), len(result.rejects)
        )
    return {
        "duplicate": False,
        "count": len(result.valid),
        "rejected": len(result.rejects),
        "rejects_stored": stored,
        "inserted": counts.inserted,
        "updated": counts.updated,
        "unchanged": counts.unchanged,
    }


def mark_failed(app: Runtime, batch_id: uuid.UUID, reason: str) -> None:
    """Fail the batch with the reason (truncated) and log the outcome."""
    changed = fail_batch(app.database.connection(), batch_id, reason[:MAX_ERROR_LENGTH])
    log_event(
        logger,
        "batch_failed",
        level=logging.ERROR,
        batch_id=str(batch_id),
        error=reason,
        changed=changed,
    )
