"""batch-status queries on real PostgreSQL 16: NULL funnel counters, latest run wins, rejects."""

import csv
import io
import json
import os
import uuid
from typing import Any

import pytest

from lambdas.batch_status import handler as module
from lambdas.shared.batches import create_batch, finish_chunk, start_loading, try_complete
from lambdas.shared.config import BatchStatusConfig, DbConfig
from lambdas.shared.db import Database, transaction
from lambdas.shared.loading import store_rejects
from lambdas.shared.reject_report import DOWNLOAD_ROW_LIMIT, download
from lambdas.shared.status import REJECT_PREVIEW_LIMIT, batch_status
from lambdas.shared.validation import REQUIRED_COLUMNS, Record, check_header, validate_rows

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
    assert document["rejects_stored"] == REJECT_COUNT
    assert document["reject_summary"] == [
        {"problem": "other", "rows": REJECT_COUNT, "first_line": 2, "example": "reason 2"}
    ]


def validator_rejects(batch_id: uuid.UUID, conn: Any) -> None:
    good = [str(uuid.uuid4()), "A", "a@example.invalid", "50000", "700", "Salaried", "30"]
    rows = [
        [*good[:6], "12"],
        ["not-a-uuid", *good[1:4], "990", *good[5:]],
        ["=HYPERLINK(1)", *good[1:]],
        good[:3],
    ]
    records = [Record(line, fields, ",".join(fields)) for line, fields in enumerate(rows, 2)]
    result = validate_rows(records, check_header(list(REQUIRED_COLUMNS)))
    store_rejects(conn, batch_id, result.rejects)


def test_summary_and_download_of_validator_rejects(connect_db: Any) -> None:
    conn = connect_db()
    batch_id = create_batch(conn)
    validator_rejects(batch_id, conn)

    document = batch_status(conn, batch_id)
    text = download(conn, batch_id)

    assert document is not None
    assert document["rejects_stored"] == 4
    assert [(g["problem"], g["rows"], g["first_line"]) for g in document["reject_summary"]] == [
        ("user_id", 2, 3),
        ("age", 1, 2),
        ("credit_score", 1, 3),
        ("wrong number of fields", 1, 5),
    ]
    assert text is not None
    rows = list(csv.reader(io.StringIO(text, newline="")))
    assert rows[0] == ["line_no", "reason", "raw"]
    assert [row[0] for row in rows[1:]] == ["2", "3", "4", "5"]
    assert rows[3][1] == "user_id: '=HYPERLINK(1)' is not a UUID"
    assert rows[3][2].startswith("'=HYPERLINK(1),A,")


def test_download_is_capped_scoped_and_none_for_an_unknown_batch(connect_db: Any) -> None:
    conn = connect_db()
    batch_id = create_batch(conn)
    other = loaded_batch(conn)
    conn.run(
        "INSERT INTO rejected_rows (batch_id, line_no, reason, raw)"
        " SELECT :id, n, 'age: missing', 'raw' FROM generate_series(:last, 2, -1) AS n",
        id=batch_id,
        last=DOWNLOAD_ROW_LIMIT + 11,
    )

    text = download(conn, batch_id)

    assert text is not None
    lines = text.splitlines()
    assert len(lines) == 1 + DOWNLOAD_ROW_LIMIT
    assert lines[1] == "2,age: missing,raw"
    assert download(conn, uuid.uuid4()) is None
    assert other_reasons(download(conn, other)) == {f"reason {n}" for n in range(2, 10)}
    empty = create_batch(conn)
    assert download(conn, empty) == "line_no,reason,raw\r\n"


def other_reasons(text: str | None) -> set[str]:
    assert text is not None
    return {row[1] for row in list(csv.reader(io.StringIO(text, newline="")))[1:]}


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


def test_completed_run_exposes_every_stage_counter(connect_db: Any) -> None:
    conn = connect_db()
    batch_id = loaded_batch(conn)
    conn.run(
        "INSERT INTO pipeline_runs (batch_id, total_pairs, stage1_pairs, stage1_near_miss,"
        " stage2_clear, stage2_borderline, stage2_reject, llm_cohorts, cache_hits, llm_calls,"
        " llm_tokens, stage3_eligible, stage3_not_eligible, unresolved_budget, unresolved_error,"
        " final_matches, finished_at) VALUES (:id, 1000, 400, 150, 250, 100, 50, 12, 4, 2, 3100,"
        " 60, 30, 6, 4, 310, now())",
        id=batch_id,
    )

    document = batch_status(conn, batch_id)

    assert document is not None
    stages = document["funnel"]
    assert (stages["stage1_near_miss"], stages["stage2_reject"]) == (150, 50)
    assert (stages["stage3_eligible"], stages["stage3_not_eligible"]) == (60, 30)
    assert (stages["unresolved_budget"], stages["unresolved_error"]) == (6, 4)
    assert stages["final_matches"] == stages["stage2_clear"] + stages["stage3_eligible"]
    assert stages["finished_at"] is not None


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


def test_handler_serves_the_rejects_csv_over_a_real_connection(
    connect_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = connect_db()
    batch_id = create_batch(conn)
    validator_rejects(batch_id, conn)
    config = DbConfig("db", 5432, "loans", "u", "pw", ca_bundle=None)
    app = module.Runtime(BatchStatusConfig(config), Database(config, connector=lambda _c: conn))
    monkeypatch.setattr(module, "runtime", lambda: app)
    event = {
        "requestContext": {"http": {"method": "GET"}},
        "queryStringParameters": {"batch_id": str(batch_id), "download": "rejects"},
    }

    response = module.handler(event, None)

    assert response["statusCode"] == 200
    assert response["headers"]["content-type"] == "text/csv; charset=utf-8"
    assert response["body"].count("\r\n") == 5
