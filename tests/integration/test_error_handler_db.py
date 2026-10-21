"""Workflow E's SQL on PostgreSQL 16: the failure is stored first, the alert outcome after."""

import os
from collections.abc import Callable
from typing import Any

import pytest
from pg8000.exceptions import DatabaseError

from tests.workflow_b_helpers import node_query, single_row
from tests.workflow_e_helpers import (
    FAILED_NODE,
    INSERT_NODE,
    INSERT_PARAMS,
    LOAD_NODE,
    OUTCOME_PARAMS,
    SENT_NODE,
    WORKFLOW_E,
)

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set")

FAILURE = {
    "workflow_id": "wfbmatching001",
    "workflow_name": "B · Matching",
    "execution_id": "77",
    "execution_url": "http://localhost:5678/workflow/wfbmatching001/executions/77",
    "node_name": "Stage 1 · SQL pre-filter",
    "mode": "webhook",
    "error_message": "boom",
    "error_stack": "Error: boom",
}


@pytest.fixture
def conn(connect_db: Callable[[], Any]) -> Any:
    return connect_db()


def insert(conn: Any, **overrides: Any) -> dict[str, Any]:
    query = node_query(INSERT_NODE, INSERT_PARAMS, WORKFLOW_E)
    return single_row(conn, conn.run(query, **{**FAILURE, **overrides}))


def stored(conn: Any, record_id: str) -> dict[str, Any]:
    rows = conn.run("SELECT * FROM n8n_errors WHERE id = :id", id=int(record_id))
    return single_row(conn, rows)


def test_insert_stores_the_failure_and_returns_its_id_as_text(conn: Any) -> None:
    returned = insert(conn)
    row = stored(conn, returned["id"])
    assert isinstance(returned["id"], str)
    assert row["workflow_name"] == "B · Matching"
    assert row["node_name"] == "Stage 1 · SQL pre-filter"
    assert row["error_message"] == "boom"
    assert row["alert_sent_at"] is None
    assert row["alert_error"] is None


def test_insert_turns_empty_optional_fields_into_null(conn: Any) -> None:
    row = stored(conn, insert(conn, execution_id="", node_name="", error_stack="")["id"])
    assert (row["execution_id"], row["node_name"], row["error_stack"]) == (None, None, None)


def test_insert_refuses_an_empty_message_or_workflow_name(conn: Any) -> None:
    with pytest.raises(DatabaseError, match="check constraint"):
        insert(conn, error_message="  ")
    with pytest.raises(DatabaseError, match="check constraint"):
        insert(conn, workflow_name="")


def test_alert_sent_is_recorded_with_the_ses_message_id(conn: Any) -> None:
    record_id = insert(conn)["id"]
    query = node_query(SENT_NODE, OUTCOME_PARAMS, WORKFLOW_E)
    conn.run(query, record_id=record_id, detail="msg-123")
    row = stored(conn, record_id)
    assert row["alert_sent_at"] is not None
    assert row["ses_message_id"] == "msg-123"
    assert row["alert_error"] is None


def test_alert_failure_is_recorded_and_truncated(conn: Any) -> None:
    record_id = insert(conn)["id"]
    query = node_query(FAILED_NODE, OUTCOME_PARAMS, WORKFLOW_E)
    conn.run(query, record_id=record_id, detail="x" * 3000)
    row = stored(conn, record_id)
    assert row["alert_sent_at"] is None
    assert len(row["alert_error"]) == 1000


def test_outcome_updates_with_no_record_id_change_nothing(conn: Any) -> None:
    record_id = insert(conn)["id"]
    for name in (SENT_NODE, FAILED_NODE):
        query = node_query(name, OUTCOME_PARAMS, WORKFLOW_E)
        assert conn.run(query, record_id="", detail="x") == []
    assert stored(conn, record_id)["alert_sent_at"] is None


def test_a_row_cannot_be_both_sent_and_failed(conn: Any) -> None:
    record_id = insert(conn)["id"]
    conn.run(node_query(SENT_NODE, OUTCOME_PARAMS, WORKFLOW_E), record_id=record_id, detail="m")
    with pytest.raises(DatabaseError, match="check constraint"):
        conn.run(
            node_query(FAILED_NODE, OUTCOME_PARAMS, WORKFLOW_E), record_id=record_id, detail="e"
        )


def test_load_recipient_returns_the_sender_and_the_first_test_alias(conn: Any) -> None:
    row = single_row(conn, conn.run(node_query(LOAD_NODE, {}, WORKFLOW_E)))
    assert row["from_address"] == "mrrssoni12@gmail.com"
    assert row["to_address"] == "mrrssoni12@gmail.com"
    assert row["test_inbox_aliases"] == [
        "mrrssoni12@gmail.com",
        "mrrssoni12+one@gmail.com",
        "mrrssoni12+two@gmail.com",
    ]
