"""batch-status queries on real PostgreSQL 16: NULL funnel counters, latest run wins."""

import json
import os
import uuid
from typing import Any

import pytest

from lambdas.batch_status import handler as module
from lambdas.shared.batches import create_batch, finish_chunk, start_loading, try_complete
from lambdas.shared.config import BatchStatusConfig, DbConfig
from lambdas.shared.db import Database, transaction
from lambdas.shared.status import REJECT_PREVIEW_LIMIT, batch_status

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set")

REJECT_COUNT = 8


def add_users(conn: Any, batch_id: uuid.UUID, count: int) -> list[uuid.UUID]:
    ids = [uuid.uuid4() for _ in range(count)]
    for user_id in ids:
        conn.run(
            "INSERT INTO users (user_id, name, email, monthly_income, credit_score,"
            " employment_status, age, batch_id) VALUES (:id, 'A', 'a@example.invalid', 50000, 700,"
            " 'Salaried', 30, :batch)",
            id=user_id,
            batch=batch_id,
        )
    return ids


def add_product(conn: Any) -> int:
    rows = conn.run(
        "INSERT INTO loan_products (source, product_name) VALUES ('test', 'P') RETURNING id"
    )
    return int(rows[0][0])


def loaded_batch(conn: Any) -> uuid.UUID:
    batch_id = create_batch(conn)
    assert start_loading(conn, batch_id, 1)
    for line in range(2, 2 + REJECT_COUNT):
        conn.run(
            "INSERT INTO rejected_rows (batch_id, line_no, reason) VALUES (:id, :line, :reason)",
            id=batch_id,
            line=line,
            reason=f"reason {line}",
        )
    with transaction(conn):
        conn.run(
            "INSERT INTO chunk_loads (batch_id, chunk_no, rows_ok, rows_rejected)"
            " VALUES (:id, 0, 0, 0)",
            id=batch_id,
        )
        finish_chunk(conn, batch_id, 0, rows_ok=3, rows_rejected=REJECT_COUNT)
    assert try_complete(conn, batch_id)
    return batch_id


def test_loaded_batch_reports_counters_rejects_and_no_funnel(connect_db: Any) -> None:
    conn = connect_db()
    batch_id = loaded_batch(conn)

    document = batch_status(conn, batch_id)

    assert document is not None
    assert document["status"] == "processed"
    assert (document["total_chunks"], document["chunks_done"]) == (1, 1)
    assert (document["rows_ok"], document["rows_rejected"]) == (3, REJECT_COUNT)
    assert document["first_rejects"] == [
        {"line_no": line, "reason": f"reason {line}"} for line in range(2, 2 + REJECT_PREVIEW_LIMIT)
    ]
    assert (document["matches"], document["notified"]) == (0, 0)
    assert document["funnel"] is None


def test_matches_notified_and_latest_funnel_run(connect_db: Any) -> None:
    conn = connect_db()
    batch_id = loaded_batch(conn)
    users = add_users(conn, batch_id, 3)
    product = add_product(conn)
    for user_id in users:
        conn.run(
            "INSERT INTO matches (user_id, product_id, stage, reason, batch_id)"
            " VALUES (:user, :product, 'rules', 'ok', :batch)",
            user=user_id,
            product=product,
            batch=batch_id,
        )
    conn.run("UPDATE matches SET notified_at = now() WHERE user_id = :user", user=users[0])
    conn.run("INSERT INTO pipeline_runs (batch_id, total_pairs) VALUES (:id, 111)", id=batch_id)
    conn.run(
        "INSERT INTO pipeline_runs (batch_id, total_pairs, stage1_pairs, stage_ms)"
        " VALUES (:id, 300, 120, CAST(:ms AS jsonb))",
        id=batch_id,
        ms='{"stage1": 42}',
    )

    document = batch_status(conn, batch_id)

    assert document is not None
    assert (document["matches"], document["notified"]) == (3, 1)
    assert document["funnel"]["total_pairs"] == 300
    assert document["funnel"]["stage1_pairs"] == 120
    assert document["funnel"]["stage2_clear"] is None
    assert document["funnel"]["stage_ms"] == {"stage1": 42}
    assert document["funnel"]["finished_at"] is None
    json.dumps(document)


def test_counts_are_scoped_to_the_requested_batch(connect_db: Any) -> None:
    conn = connect_db()
    first = loaded_batch(conn)
    second = loaded_batch(conn)
    conn.run("INSERT INTO pipeline_runs (batch_id, total_pairs) VALUES (:id, 5)", id=first)

    other = batch_status(conn, second)

    assert other is not None
    assert other["funnel"] is None
    assert other["first_rejects"][0]["line_no"] == 2


def test_failed_batch_exposes_its_error_and_unknown_batch_is_none(connect_db: Any) -> None:
    conn = connect_db()
    batch_id = create_batch(conn)
    conn.run(
        "UPDATE upload_batches SET status = 'failed', error = 'split failed' WHERE id = :id",
        id=batch_id,
    )

    document = batch_status(conn, batch_id)

    assert document is not None
    assert (document["status"], document["error"]) == ("failed", "split failed")
    assert document["total_chunks"] is None
    assert batch_status(conn, uuid.uuid4()) is None


def test_handler_over_a_real_connection(connect_db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = connect_db()
    batch_id = loaded_batch(conn)
    config = DbConfig("db", 5432, "loans", "u", "pw", ca_bundle=None)
    app = module.Runtime(BatchStatusConfig(config), Database(config, connector=lambda _c: conn))
    monkeypatch.setattr(module, "runtime", lambda: app)
    event = {
        "requestContext": {"http": {"method": "GET"}},
        "queryStringParameters": {"batch_id": str(batch_id)},
    }

    response = module.handler(event, None)

    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    counters = (body["status"], body["rows_ok"], body["rows_rejected"])
    assert counters == ("processed", 3, REJECT_COUNT)
