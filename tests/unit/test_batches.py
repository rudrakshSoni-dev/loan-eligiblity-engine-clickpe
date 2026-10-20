"""Batch transition rules and the branching of each ledger call, with a scripted connection."""

import uuid
from itertools import pairwise
from typing import Any

import pytest

from lambdas.shared.batches import (
    FAILABLE,
    TRANSITIONS,
    BatchStateError,
    BatchStatus,
    InvalidTransitionError,
    check_transition,
    claim_chunk,
    create_batch,
    fail_batch,
    finish_chunk,
    start_loading,
    transition,
    try_complete,
    upload_key,
)

BATCH = uuid.UUID("00000000-0000-4000-8000-000000000001")


class ScriptedConnection:
    def __init__(self, *results: list[list[Any]]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, sql: str, **params: Any) -> list[list[Any]]:
        self.calls.append((sql, params))
        return self.results.pop(0) if self.results else []


def test_every_status_has_a_transition_entry() -> None:
    assert set(TRANSITIONS) == set(BatchStatus)
    assert FAILABLE == ("loading", "matching", "notifying", "pending")


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (BatchStatus.PENDING, BatchStatus.PROCESSED),
        (BatchStatus.PROCESSED, BatchStatus.LOADING),
        (BatchStatus.FAILED, BatchStatus.LOADING),
        (BatchStatus.NOTIFIED, BatchStatus.MATCHING),
        (BatchStatus.LOADING, BatchStatus.LOADING),
    ],
)
def test_invalid_transition_is_rejected_before_any_sql(
    current: BatchStatus, target: BatchStatus
) -> None:
    conn = ScriptedConnection()
    with pytest.raises(InvalidTransitionError):
        transition(conn, BATCH, current, target)
    assert conn.calls == []


def test_happy_path_is_a_chain_of_allowed_transitions() -> None:
    chain = ["pending", "loading", "processed", "matching", "matched", "notifying", "notified"]
    for current, target in pairwise(chain):
        check_transition(BatchStatus(current), BatchStatus(target))


def test_transition_is_conditional_on_the_expected_status() -> None:
    conn = ScriptedConnection([[BATCH]], [])
    assert transition(conn, BATCH, BatchStatus.PROCESSED, BatchStatus.MATCHING)
    assert not transition(conn, BATCH, BatchStatus.PROCESSED, BatchStatus.MATCHING)
    sql, params = conn.calls[0]
    assert "AND status = :current" in sql
    assert params == {"id": BATCH, "current": "processed", "target": "matching"}


def test_create_batch_uses_the_upload_key_of_its_own_id() -> None:
    conn = ScriptedConnection()
    batch_id = create_batch(conn)
    assert conn.calls[0][1] == {"id": batch_id, "key": f"uploads/{batch_id}.csv"}
    assert upload_key(batch_id) == f"uploads/{batch_id}.csv"


def test_start_loading_first_message_moves_pending_to_loading() -> None:
    conn = ScriptedConnection([[BATCH]])
    assert start_loading(conn, BATCH, 4)
    assert len(conn.calls) == 1


@pytest.mark.parametrize(("status", "expected"), [("loading", True), ("failed", False)])
def test_start_loading_later_messages_follow_the_stored_status(status: str, expected: bool) -> None:
    conn = ScriptedConnection([], [[status, 4]])
    assert start_loading(conn, BATCH, 4) is expected


def test_start_loading_refuses_a_different_chunk_count() -> None:
    conn = ScriptedConnection([], [["loading", 4]])
    with pytest.raises(BatchStateError, match="has 4 chunks, message says 5"):
        start_loading(conn, BATCH, 5)


def test_start_loading_refuses_an_unknown_batch() -> None:
    conn = ScriptedConnection([], [])
    with pytest.raises(BatchStateError, match="does not exist"):
        start_loading(conn, BATCH, 1)


def test_claim_complete_and_fail_report_whether_a_row_came_back() -> None:
    conn = ScriptedConnection([[0]], [], [[BATCH]], [], [[BATCH]], [])
    assert claim_chunk(conn, BATCH, 0)
    assert not claim_chunk(conn, BATCH, 0)
    assert try_complete(conn, BATCH)
    assert not try_complete(conn, BATCH)
    assert fail_batch(conn, BATCH, "bad header")
    assert not fail_batch(conn, BATCH, "bad header")
    assert conn.calls[-1][1]["failable"] == list(FAILABLE)


def test_finish_chunk_updates_ledger_and_display_counters() -> None:
    conn = ScriptedConnection()
    finish_chunk(conn, BATCH, 2, rows_ok=4990, rows_rejected=10)
    ledger, counters = conn.calls
    assert "UPDATE chunk_loads" in ledger[0]
    assert "chunks_done = chunks_done + 1" in counters[0]
    assert counters[1] == {"id": BATCH, "ok": 4990, "rejected": 10}
