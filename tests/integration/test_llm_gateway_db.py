"""The LLM Gateway's SQL on real PostgreSQL 16: the 24 h budget read and the per-attempt ledger row.

The budget query's output is fed into the exported `Prepare` node, so the refusal at the daily
budget is checked with what the database really returns (jsonb numbers, missing models).
"""

import os
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from pg8000.exceptions import DatabaseError

from tests.workflow_b_helpers import NODE_BINARY, new_batch, new_run, node_query, single_row
from tests.workflow_gateway_helpers import (
    BUDGET_NODE,
    FALLBACK,
    GATEWAY,
    LOG_NODE,
    LOG_PARAMS,
    PREPARE_NODE,
    PRIMARY,
    gateway_request,
    js_constant,
    ok_reply,
    prepare,
    run_gateway,
    status_reply,
)

pytestmark = [
    pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set"),
    pytest.mark.skipif(NODE_BINARY is None, reason="node not installed"),
]


def usage(conn: Any) -> dict[str, Any]:
    row = single_row(conn, conn.run(node_query(BUDGET_NODE, {}, GATEWAY)))
    found: dict[str, Any] = row["usage"]
    return found


def call(conn: Any, model: str, tokens: tuple[int | None, int | None], age: str = "0") -> None:
    conn.run(
        "INSERT INTO llm_calls (purpose, model, prompt_tokens, completion_tokens, status,"
        " created_at) VALUES ('gateway_check', :m, :p, :c, 200, now() - CAST(:age AS interval))",
        m=model,
        p=tokens[0],
        c=tokens[1],
        age=f"{age} hours",
    )


def log_row(conn: Any, row: dict[str, Any]) -> list[Any]:
    params = {f"p{i}": value for i, value in enumerate(row.values(), start=1)}
    found: list[Any] = conn.run(node_query(LOG_NODE, LOG_PARAMS, GATEWAY), **params)[0]
    return found


def test_budget_read_is_empty_on_a_fresh_ledger(connect_db: Callable[[], Any]) -> None:
    assert usage(connect_db()) == {}


def test_budget_read_sums_the_last_24_hours_per_model(connect_db: Callable[[], Any]) -> None:
    conn = connect_db()
    call(conn, PRIMARY, (1000, 200))
    call(conn, PRIMARY, (None, None))
    call(conn, PRIMARY, (5000, 5000), age="25")
    call(conn, FALLBACK, (30, 7), age="23")

    assert usage(conn) == {
        PRIMARY: {"tokens": 1200, "calls": 2},
        FALLBACK: {"tokens": 37, "calls": 1},
    }


def test_prepare_refuses_on_the_real_ledger_once_both_models_are_spent(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    daily = js_constant(PREPARE_NODE, "DAILY_TOKEN_BUDGET")
    call(conn, PRIMARY, (daily, 0))

    switched = prepare(gateway_request(), {"usage": usage(conn)})
    call(conn, FALLBACK, (daily - 10, 0))
    refused = prepare(gateway_request(), {"usage": usage(conn)})

    assert (switched["next"], switched["model"], switched["fallback_reason"]) == (
        "call",
        FALLBACK,
        "budget",
    )
    assert refused["next"] == "return"
    assert refused["outcome"]["error_kind"] == "budget"


def test_every_attempt_becomes_one_ledger_row_with_run_and_batch(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    request = gateway_request(batch_id=str(batch_id), run_id=run_id)

    run = run_gateway(request, [status_reply(429, "3"), ok_reply(tokens=(1493, 762))])
    for row in run.logged:
        log_row(conn, row)

    assert conn.run(
        "SELECT purpose, model, prompt_tokens, completion_tokens, status, latency_ms, batch_id,"
        " run_id FROM llm_calls ORDER BY id"
    ) == [
        ["gateway_check", PRIMARY, None, None, 429, None, batch_id, run_id],
        ["gateway_check", PRIMARY, 1493, 762, 200, 250, batch_id, run_id],
    ]
    assert usage(conn) == {PRIMARY: {"tokens": 2255, "calls": 2}}


def test_ledger_row_without_batch_is_allowed_and_a_run_without_batch_is_refused(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    run = run_gateway(gateway_request(), [ok_reply()])

    assert log_row(conn, run.logged[0])[0].isdigit()
    orphan = {**run.logged[0], "run_id": new_run(conn, new_batch(conn))}
    with pytest.raises(DatabaseError, match="llm_calls_check"):
        log_row(conn, orphan)
    assert conn.run("SELECT count(*), bool_and(batch_id IS NULL) FROM llm_calls") == [[1, True]]


def test_ledger_row_needs_a_known_batch(connect_db: Callable[[], Any]) -> None:
    conn = connect_db()
    run = run_gateway(gateway_request(), [ok_reply()])

    with pytest.raises(DatabaseError, match="foreign key"):
        log_row(conn, {**run.logged[0], "batch_id": str(uuid.uuid4())})
