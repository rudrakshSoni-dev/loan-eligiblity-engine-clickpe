"""Workflow B persist step on real PostgreSQL 16: the exported insert, finalize and failure SQL.

Stages 1 to 3 run first with their own exported nodes, so the pairs persisted are the ones the
workflow would produce. Groq is replaced by fake replies shaped like real ones.
"""

import os
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from pg8000.exceptions import DatabaseError

from tests.integration.test_stage3_cohorts_db import (
    funnel_to_borderline,
    groq_reply,
    run_stage3,
    soft_product,
)
from tests.workflow_b_helpers import (
    NODE_BINARY,
    TIMED_PARAMS,
    add_user,
    new_batch,
    new_run,
    node_query,
    single_row,
)

pytestmark = [
    pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set"),
    pytest.mark.skipif(NODE_BINARY is None, reason="node not installed"),
]

INSERT_NODE = "Persist · Insert matches"
FINALIZE_NODE = "Persist · Finalize run + mark matched"
FAIL_NODE = "Fail · Mark batch failed (Persist)"
INSERT_PARAMS = {"$1": ":run_id", "$2": ":batch_id"}
FAIL_PARAMS = {"$1": ":run_id", "$2": ":batch_id", "$3": ":message"}


def insert_matches(conn: Any, run_id: int, batch_id: uuid.UUID) -> dict[str, Any]:
    rows = conn.run(node_query(INSERT_NODE, INSERT_PARAMS), run_id=str(run_id), batch_id=batch_id)
    return single_row(conn, rows)


def finalize(conn: Any, run_id: int, batch_id: uuid.UUID, started_at: Any) -> dict[str, Any]:
    rows = conn.run(
        node_query(FINALIZE_NODE, TIMED_PARAMS),
        run_id=str(run_id),
        batch_id=batch_id,
        started_at=started_at,
    )
    return single_row(conn, rows)


def run_persist(conn: Any, run_id: int, batch_id: uuid.UUID) -> dict[str, Any]:
    inserted = insert_matches(conn, run_id, batch_id)
    closed = finalize(conn, run_id, batch_id, inserted["persist_started_at"])
    return {**inserted, **closed}


def stored_matches(conn: Any) -> dict[tuple[uuid.UUID, int], tuple[str, str, uuid.UUID]]:
    rows = conn.run("SELECT user_id, product_id, stage, reason, batch_id FROM matches")
    return {(r[0], r[1]): (r[2], r[3], r[4]) for r in rows}


def mixed_batch(conn: Any) -> tuple[uuid.UUID, int, dict[str, uuid.UUID], int]:
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    product = soft_product(conn)
    users = {
        "clear": add_user(conn, batch_id, 60000, 760),
        "llm_yes": add_user(conn, batch_id, 60000, 690),
        "llm_no": add_user(conn, batch_id, 29000, 740),
        "reject": add_user(conn, batch_id, 20000, 600),
    }
    funnel_to_borderline(conn, run_id, batch_id)
    return batch_id, run_id, users, product


def test_only_clear_matches_and_llm_eligible_pairs_become_matches(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id, run_id, users, product = mixed_batch(conn)
    run_stage3(conn, run_id, batch_id, groq_reply)

    result = run_persist(conn, run_id, batch_id)

    found = stored_matches(conn)
    assert set(found) == {(users["clear"], product), (users["llm_yes"], product)}
    assert found[(users["clear"], product)][0] == "rules"
    assert found[(users["llm_yes"], product)] == ("llm", "quoted", batch_id)
    assert (
        found[(users["clear"], product)][1]
        == conn.run(
            "SELECT stage2_reason FROM match_candidates WHERE run_id = :r AND user_id = :u",
            r=run_id,
            u=users["clear"],
        )[0][0]
    )
    assert (result["qualifying"], result["inserted"], result["final_matches"]) == (2, 2, 2)
    assert result["final_matches"] == result["stage2_clear"] + result["stage3_eligible"]


def test_finalize_closes_the_run_and_marks_the_batch_matched(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id, run_id, _, _ = mixed_batch(conn)
    run_stage3(conn, run_id, batch_id, groq_reply)

    result = run_persist(conn, run_id, batch_id)

    assert result["batch_marked"] == 1 and result["persist_ms"] >= 0
    assert conn.run(
        "SELECT b.status, r.finished_at IS NOT NULL, r.stage_ms ? 'persist', r.final_matches"
        " FROM upload_batches b JOIN pipeline_runs r ON r.batch_id = b.id"
    ) == [["matched", True, True, 2]]


def test_rerun_inserts_nothing_and_keeps_the_first_measurements(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id, run_id, _, _ = mixed_batch(conn)
    run_stage3(conn, run_id, batch_id, groq_reply)
    run_persist(conn, run_id, batch_id)
    before = conn.run("SELECT finished_at, stage_ms FROM pipeline_runs")

    second = run_persist(conn, run_id, batch_id)

    assert (second["inserted"], second["final_matches"], second["batch_marked"]) == (0, 2, 0)
    assert conn.run("SELECT finished_at, stage_ms FROM pipeline_runs") == before
    assert conn.run("SELECT count(*) FROM matches") == [[2]]


def test_an_existing_match_keeps_its_batch_and_notification_time(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    earlier = new_batch(conn, "notified")
    batch_id, run_id, users, product = mixed_batch(conn)
    conn.run(
        "INSERT INTO matches (user_id, product_id, stage, reason, batch_id, notified_at)"
        " VALUES (:u, :p, 'rules', 'earlier reason', :b, '2026-10-01 10:00:00+00')",
        u=users["clear"],
        p=product,
        b=earlier,
    )
    run_stage3(conn, run_id, batch_id, groq_reply)

    result = run_persist(conn, run_id, batch_id)

    assert (result["qualifying"], result["inserted"], result["final_matches"]) == (2, 1, 2)
    assert conn.run(
        "SELECT reason, batch_id, notified_at IS NOT NULL FROM matches WHERE user_id = :u",
        u=users["clear"],
    ) == [["earlier reason", earlier, True]]


def test_unresolved_pairs_are_not_matches(connect_db: Callable[[], Any]) -> None:
    conn = connect_db()
    batch_id, run_id, users, product = mixed_batch(conn)

    def rate_limited(_: dict[str, Any]) -> dict[str, Any]:
        return {"statusCode": 429, "headers": {"retry-after": "21"}, "body": {"error": "limit"}}

    stage3 = run_stage3(conn, run_id, batch_id, rate_limited)
    assert stage3["unresolved_error"] == 2

    result = run_persist(conn, run_id, batch_id)

    assert set(stored_matches(conn)) == {(users["clear"], product)}
    assert (result["final_matches"], result["unresolved_error"]) == (1, 2)


def test_a_run_with_no_qualifying_pair_records_a_measured_zero(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    soft_product(conn)
    add_user(conn, batch_id, 20000, 600)
    funnel_to_borderline(conn, run_id, batch_id)
    run_stage3(conn, run_id, batch_id, reply=None)

    result = run_persist(conn, run_id, batch_id)

    assert (result["qualifying"], result["final_matches"], result["batch_marked"]) == (0, 0, 1)
    assert conn.run("SELECT count(*) FROM matches") == [[0]]


def test_a_pair_missing_from_matches_fails_the_funnel_check_and_leaves_the_batch_matching(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id, run_id, _, _ = mixed_batch(conn)
    run_stage3(conn, run_id, batch_id, groq_reply)
    inserted = insert_matches(conn, run_id, batch_id)
    conn.run("DELETE FROM matches WHERE stage = 'llm'")

    with pytest.raises(DatabaseError, match="pipeline_runs_final_matches_funnel"):
        finalize(conn, run_id, batch_id, inserted["persist_started_at"])

    assert conn.run(
        "SELECT b.status, r.finished_at IS NULL, r.final_matches IS NULL"
        " FROM upload_batches b JOIN pipeline_runs r ON r.batch_id = b.id"
    ) == [["matching", True, True]]


def test_finalize_does_not_touch_a_batch_that_is_no_longer_matching(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id, run_id, _, _ = mixed_batch(conn)
    run_stage3(conn, run_id, batch_id, groq_reply)
    inserted = insert_matches(conn, run_id, batch_id)
    conn.run("UPDATE upload_batches SET status = 'failed', error = 'x' WHERE id = :b", b=batch_id)

    closed = finalize(conn, run_id, batch_id, inserted["persist_started_at"])

    assert closed["batch_marked"] == 0
    assert conn.run("SELECT status FROM upload_batches") == [["failed"]]


def test_failure_branch_names_the_persist_step(connect_db: Callable[[], Any]) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)

    closed = conn.run(
        node_query(FAIL_NODE, FAIL_PARAMS), run_id=str(run_id), batch_id=batch_id, message="boom"
    )

    assert closed == [[str(run_id), str(batch_id)]]
    assert conn.run(
        "SELECT b.status, b.error, r.finished_at IS NOT NULL FROM upload_batches b"
        " JOIN pipeline_runs r ON r.batch_id = b.id"
    ) == [["failed", "matching persist failed: boom", True]]
