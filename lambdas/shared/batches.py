"""Upload batch lifecycle, the chunk idempotency ledger and the exactly-once completion check.

Every status change is a conditional `UPDATE … WHERE status = <expected> RETURNING`, so two
concurrent callers can never both apply the same transition: the row lock makes the second wait,
and Postgres re-checks the WHERE clause against the committed row, which no longer matches.

Chunk protocol for load-chunk (one SQS message = one chunk, delivered at least once):
    1. start_loading(conn, batch_id, total_chunks)            autocommit, before the chunk
    2. with transaction(conn):
           if claim_chunk(...):  load rows …; finish_chunk(...)
    3. try_complete(conn, batch_id)                           autocommit, after the commit

Step 3 runs even when step 2 found a duplicate, so a Lambda that crashed between its commit and
its completion check is finished by the redelivered message.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from enum import StrEnum

from lambdas.shared.db import Connection

UPLOAD_PREFIX = "uploads/"


class BatchStatus(StrEnum):
    """Every status an upload batch can have, as stored in `upload_batches.status`."""

    PENDING = "pending"
    LOADING = "loading"
    PROCESSED = "processed"
    FAILED = "failed"
    MATCHING = "matching"
    MATCHED = "matched"
    NOTIFYING = "notifying"
    NOTIFIED = "notified"


TRANSITIONS: Mapping[BatchStatus, frozenset[BatchStatus]] = {
    BatchStatus.PENDING: frozenset({BatchStatus.LOADING, BatchStatus.FAILED}),
    BatchStatus.LOADING: frozenset({BatchStatus.PROCESSED, BatchStatus.FAILED}),
    BatchStatus.PROCESSED: frozenset({BatchStatus.MATCHING}),
    BatchStatus.MATCHING: frozenset({BatchStatus.MATCHED, BatchStatus.FAILED}),
    BatchStatus.MATCHED: frozenset({BatchStatus.NOTIFYING}),
    BatchStatus.NOTIFYING: frozenset({BatchStatus.NOTIFIED, BatchStatus.FAILED}),
    BatchStatus.FAILED: frozenset(),
    BatchStatus.NOTIFIED: frozenset(),
}

FAILABLE = tuple(
    sorted(s.value for s, targets in TRANSITIONS.items() if BatchStatus.FAILED in targets)
)


class InvalidTransitionError(ValueError):
    """The requested status change is not in TRANSITIONS; no SQL was sent."""


class BatchStateError(Exception):
    """The batch row contradicts the message being processed (unknown id, other chunk count)."""


def upload_key(batch_id: uuid.UUID) -> str:
    """Return the only S3 key a batch's CSV may have: `uploads/{batch_id}.csv`."""
    return f"{UPLOAD_PREFIX}{batch_id}.csv"


def check_transition(current: BatchStatus, target: BatchStatus) -> None:
    """Raise InvalidTransitionError unless TRANSITIONS allows current → target."""
    if target not in TRANSITIONS[current]:
        raise InvalidTransitionError(f"batch status cannot change from {current} to {target}")


def create_batch(conn: Connection) -> uuid.UUID:
    """Insert a new `pending` batch row and return its id."""
    batch_id = uuid.uuid4()
    conn.run(
        "INSERT INTO upload_batches (id, s3_key) VALUES (:id, :key)",
        id=batch_id,
        key=upload_key(batch_id),
    )
    return batch_id


def transition(
    conn: Connection, batch_id: uuid.UUID, current: BatchStatus, target: BatchStatus
) -> bool:
    """Move the batch from `current` to `target`; False if it was no longer in `current`."""
    check_transition(current, target)
    rows = conn.run(
        "UPDATE upload_batches SET status = :target WHERE id = :id AND status = :current"
        " RETURNING id",
        id=batch_id,
        current=current.value,
        target=target.value,
    )
    return bool(rows)


def fail_batch(conn: Connection, batch_id: uuid.UUID, error: str) -> bool:
    """Mark the batch failed with a reason; False if it is already failed or past failing."""
    rows = conn.run(
        "UPDATE upload_batches SET status = 'failed', error = :error"
        " WHERE id = :id AND status = ANY(CAST(:failable AS text[])) RETURNING id",
        id=batch_id,
        error=error,
        failable=list(FAILABLE),
    )
    return bool(rows)


def start_loading(conn: Connection, batch_id: uuid.UUID, total_chunks: int) -> bool:
    """Record the chunk count and move pending → loading; True if chunks should be loaded.

    Every chunk message calls this, so after the first one it only confirms the state. A chunk
    count that differs from the stored one means two different splits of one batch, which is
    refused rather than mixed. False means the batch already failed or finished loading.
    """
    started = conn.run(
        "UPDATE upload_batches SET status = 'loading', total_chunks = :total"
        " WHERE id = :id AND status = 'pending' RETURNING id",
        id=batch_id,
        total=total_chunks,
    )
    if started:
        return True
    rows = conn.run("SELECT status, total_chunks FROM upload_batches WHERE id = :id", id=batch_id)
    if not rows:
        raise BatchStateError(f"batch {batch_id} does not exist")
    status, stored_total = rows[0]
    if stored_total is not None and stored_total != total_chunks:
        raise BatchStateError(
            f"batch {batch_id} has {stored_total} chunks, message says {total_chunks}"
        )
    return bool(status == BatchStatus.LOADING)


def claim_chunk(conn: Connection, batch_id: uuid.UUID, chunk_no: int) -> bool:
    """Insert the ledger row inside the chunk's transaction; False means a duplicate delivery.

    A concurrent duplicate blocks on the primary key until the first transaction ends, then gets
    no row back (committed) or claims the chunk itself (rolled back).
    """
    rows = conn.run(
        "INSERT INTO chunk_loads (batch_id, chunk_no, rows_ok, rows_rejected)"
        " VALUES (:id, :chunk, 0, 0) ON CONFLICT DO NOTHING RETURNING chunk_no",
        id=batch_id,
        chunk=chunk_no,
    )
    return bool(rows)


def finish_chunk(
    conn: Connection, batch_id: uuid.UUID, chunk_no: int, rows_ok: int, rows_rejected: int
) -> None:
    """Store the chunk's counts in the ledger and add them to the batch's display counters.

    Called last in the chunk's transaction, so the batch row lock is held only briefly.
    """
    conn.run(
        "UPDATE chunk_loads SET rows_ok = :ok, rows_rejected = :rejected"
        " WHERE batch_id = :id AND chunk_no = :chunk",
        id=batch_id,
        chunk=chunk_no,
        ok=rows_ok,
        rejected=rows_rejected,
    )
    conn.run(
        "UPDATE upload_batches SET chunks_done = chunks_done + 1,"
        " rows_ok = rows_ok + :ok, rows_rejected = rows_rejected + :rejected WHERE id = :id",
        id=batch_id,
        ok=rows_ok,
        rejected=rows_rejected,
    )


def try_complete(conn: Connection, batch_id: uuid.UUID) -> bool:
    """Move loading → processed once every chunk is in the ledger; True for exactly one caller.

    Must run in autocommit after the chunk's transaction has committed. Inside the transaction,
    two last chunks could each miss the other's uncommitted ledger row and neither would finish.
    After commit, the later of the two statements sees both rows, and the row lock plus the
    status re-check stop the other from also winning.
    """
    rows = conn.run(
        "UPDATE upload_batches SET status = 'processed'"
        " WHERE id = :id AND status = 'loading'"
        " AND total_chunks = (SELECT count(*) FROM chunk_loads WHERE batch_id = :id)"
        " RETURNING id",
        id=batch_id,
    )
    return bool(rows)
