"""lambdas/shared/batches.py on real PostgreSQL 16: transitions, ledger, exactly-once completion.

Needs a superuser connection to a throwaway server, as in test_migrate_db.py:
    TEST_DB_HOST=localhost TEST_DB_PORT=55432 TEST_DB_USER=postgres TEST_DB_PASSWORD=... pytest
Each test gets a freshly migrated database that is dropped afterwards.
"""

import os
import threading
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from db.migrate import DbSettings, connect, load_migrations, migrate
from lambdas.shared.batches import (
    BatchStateError,
    BatchStatus,
    InvalidTransitionError,
    claim_chunk,
    create_batch,
    fail_batch,
    finish_chunk,
    start_loading,
    transition,
    try_complete,
)
from lambdas.shared.config import DbConfig
from lambdas.shared.db import open_connection, transaction

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set")

RACE_TRIALS = 25
RACE_CHUNKS = 6
THREAD_TIMEOUT_SECONDS = 30
BLOCKED_CLAIM_WAIT_SECONDS = 0.5


def settings(database: str) -> DbSettings:
    return DbSettings(
        host=os.environ["TEST_DB_HOST"],
        port=int(os.environ.get("TEST_DB_PORT", "5432")),
        database=database,
        user=os.environ.get("TEST_DB_USER", "postgres"),
        password=os.environ.get("TEST_DB_PASSWORD", ""),
        sslrootcert=None,
    )


@pytest.fixture
def connect_db() -> Iterator[Callable[[], Any]]:
    """Yield a factory of connections to a fresh, migrated database; close them all at the end."""
    name = f"batches_test_{uuid.uuid4().hex[:12]}"
    admin = connect(settings("postgres"))
    admin.run(f'CREATE DATABASE "{name}"')
    s = settings(name)
    config = DbConfig(s.host, s.port, name, s.user, s.password, ca_bundle=None)
    opened: list[Any] = []

    def factory() -> Any:
        conn = open_connection(config)
        opened.append(conn)
        return conn

    migrate(factory(), load_migrations())
    yield factory
    for conn in opened:
        conn.close()
    admin.run(f'DROP DATABASE "{name}" WITH (FORCE)')
    admin.close()


def batch_row(conn: Any, batch_id: uuid.UUID) -> list[Any]:
    rows = conn.run(
        "SELECT status, total_chunks, chunks_done, rows_ok, rows_rejected"
        " FROM upload_batches WHERE id = :id",
        id=batch_id,
    )
    return list(rows[0])


def load_chunk(conn: Any, batch_id: uuid.UUID, chunk_no: int, rows_ok: int = 10) -> bool:
    """The T18 protocol minus the actual row loading; returns whether the chunk was new."""
    with transaction(conn):
        claimed = claim_chunk(conn, batch_id, chunk_no)
        if claimed:
            finish_chunk(conn, batch_id, chunk_no, rows_ok=rows_ok, rows_rejected=1)
    return claimed


def new_loading_batch(conn: Any, total_chunks: int) -> uuid.UUID:
    batch_id = create_batch(conn)
    assert start_loading(conn, batch_id, total_chunks)
    return batch_id


def test_invalid_transition_is_rejected_and_the_row_is_unchanged(connect_db: Any) -> None:
    conn = connect_db()
    batch_id = create_batch(conn)
    with pytest.raises(InvalidTransitionError):
        transition(conn, batch_id, BatchStatus.PENDING, BatchStatus.PROCESSED)
    assert batch_row(conn, batch_id)[0] == "pending"


def test_stale_transition_changes_nothing(connect_db: Any) -> None:
    conn = connect_db()
    batch_id = create_batch(conn)
    assert not transition(conn, batch_id, BatchStatus.LOADING, BatchStatus.PROCESSED)
    assert batch_row(conn, batch_id)[0] == "pending"


def test_start_loading_is_repeatable_and_refuses_a_different_split(connect_db: Any) -> None:
    conn = connect_db()
    batch_id = create_batch(conn)
    assert start_loading(conn, batch_id, 3)
    assert start_loading(conn, batch_id, 3)
    with pytest.raises(BatchStateError, match="has 3 chunks"):
        start_loading(conn, batch_id, 4)
    with pytest.raises(BatchStateError, match="does not exist"):
        start_loading(conn, uuid.uuid4(), 3)
    assert batch_row(conn, batch_id)[:2] == ["loading", 3]


def test_failed_batch_stops_loading_and_cannot_be_failed_twice(connect_db: Any) -> None:
    conn = connect_db()
    batch_id = new_loading_batch(conn, 2)
    assert fail_batch(conn, batch_id, "chunk 1 poisoned")
    assert not fail_batch(conn, batch_id, "again")
    assert not start_loading(conn, batch_id, 2)
    assert conn.run("SELECT error FROM upload_batches WHERE id = :id", id=batch_id) == [
        ["chunk 1 poisoned"]
    ]


def test_duplicate_chunk_delivery_is_a_no_op(connect_db: Any) -> None:
    conn = connect_db()
    batch_id = new_loading_batch(conn, 2)
    assert load_chunk(conn, batch_id, 0)
    assert not load_chunk(conn, batch_id, 0)
    assert batch_row(conn, batch_id) == ["loading", 2, 1, 10, 1]
    assert conn.run("SELECT count(*) FROM chunk_loads WHERE batch_id = :id", id=batch_id) == [[1]]


def test_concurrent_duplicate_waits_for_the_first_delivery(connect_db: Any) -> None:
    """A second claim blocks on the ledger key: it loses if the first commits, wins on rollback."""
    first, second = connect_db(), connect_db()
    batch_id = new_loading_batch(first, 1)
    for first_commits, second_expected in ((False, True), (True, False)):
        chunk_no = int(first_commits)
        first.run("BEGIN")
        assert claim_chunk(first, batch_id, chunk_no)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(load_chunk, second, batch_id, chunk_no)
            with pytest.raises(TimeoutError):
                pending.result(timeout=BLOCKED_CLAIM_WAIT_SECONDS)
            first.run("COMMIT" if first_commits else "ROLLBACK")
            assert pending.result(timeout=THREAD_TIMEOUT_SECONDS) is second_expected


def test_completion_checked_inside_the_transaction_would_be_missed(connect_db: Any) -> None:
    """Why try_complete runs after commit: two open last chunks cannot see each other's row."""
    a, b = connect_db(), connect_db()
    batch_id = new_loading_batch(a, 2)
    a.run("BEGIN")
    b.run("BEGIN")
    assert claim_chunk(a, batch_id, 0)
    assert claim_chunk(b, batch_id, 1)
    assert not try_complete(a, batch_id)
    assert not try_complete(b, batch_id)
    a.run("COMMIT")
    b.run("COMMIT")
    assert batch_row(a, batch_id)[0] == "loading"
    assert try_complete(a, batch_id)
    assert not try_complete(b, batch_id)


def test_redelivery_after_a_crash_before_the_check_finishes_the_batch(connect_db: Any) -> None:
    conn = connect_db()
    batch_id = new_loading_batch(conn, 2)
    assert load_chunk(conn, batch_id, 0)
    assert not try_complete(conn, batch_id)
    assert load_chunk(conn, batch_id, 1)
    assert not load_chunk(conn, batch_id, 1)
    assert try_complete(conn, batch_id)
    assert not try_complete(conn, batch_id)
    assert batch_row(conn, batch_id) == ["processed", 2, 2, 20, 2]


def race_batch(connections: list[Any], batch_id: uuid.UUID, check_together: bool) -> list[bool]:
    """Load one chunk per connection in parallel threads; return each caller's completion result.

    check_together=True holds every caller at a barrier between commit and try_complete, so all
    see the full ledger and fight over the row lock. False lets commits and checks interleave
    freely, which is where a caller could see an incomplete ledger.
    """
    start = threading.Barrier(len(connections))
    committed = threading.Barrier(len(connections))

    def worker(chunk_no: int) -> bool:
        conn = connections[chunk_no]
        start.wait(THREAD_TIMEOUT_SECONDS)
        load_chunk(conn, batch_id, chunk_no)
        if check_together:
            committed.wait(THREAD_TIMEOUT_SECONDS)
        return try_complete(conn, batch_id)

    with ThreadPoolExecutor(max_workers=len(connections)) as pool:
        futures = [pool.submit(worker, n) for n in range(len(connections))]
        return [f.result(timeout=THREAD_TIMEOUT_SECONDS) for f in futures]


@pytest.mark.parametrize("check_together", [True, False], ids=["checks-aligned", "interleaved"])
def test_concurrent_finishers_complete_exactly_once(connect_db: Any, check_together: bool) -> None:
    connections = [connect_db() for _ in range(RACE_CHUNKS)]
    observer = connections[0]
    winners_per_trial = []
    for _ in range(RACE_TRIALS):
        batch_id = new_loading_batch(observer, RACE_CHUNKS)
        results = race_batch(connections, batch_id, check_together)
        winners_per_trial.append(results.count(True))
        assert batch_row(observer, batch_id) == [
            "processed",
            RACE_CHUNKS,
            RACE_CHUNKS,
            10 * RACE_CHUNKS,
            RACE_CHUNKS,
        ]
    assert winners_per_trial == [1] * RACE_TRIALS
