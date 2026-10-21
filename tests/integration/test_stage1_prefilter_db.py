"""Workflow B Stage 1 on real PostgreSQL 16, running the exact SQL stored in the workflow JSON.

The statements are read from n8n/workflows/workflow-b-matching.json, so a change made in the
n8n editor and exported is what these tests check. n8n passes positional parameters ($1, $2,
$3); the tests bind the same values by name.
"""

import json
import os
import re
import uuid
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set")

WORKFLOW = Path(__file__).resolve().parents[2] / "n8n" / "workflows" / "workflow-b-matching.json"
STAGE1_NODE = "Stage 1 · SQL pre-filter"
RECORD_NODE = "Record · Stage 1 funnel"
FAIL_NODE = "Fail · Mark batch failed (Stage 1)"
STAGE1_PARAMS = {"$1": ":run_id", "$2": ":batch_id"}
RECORD_PARAMS = {"$1": ":run_id", "$2": ":batch_id", "$3": ":started_at"}
FAIL_PARAMS = {"$1": ":run_id", "$2": ":batch_id", "$3": ":message"}

STRICT = "strict"
EXCLUDED = "excluded"


def node_query(name: str, placeholders: dict[str, str]) -> str:
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))[0]
    query: str = next(n for n in workflow["nodes"] if n["name"] == name)["parameters"]["query"]
    return re.sub(r"\$\d+", lambda m: placeholders[m.group(0)], query)


def new_batch(conn: Any, status: str = "matching") -> uuid.UUID:
    batch_id = uuid.uuid4()
    conn.run(
        "INSERT INTO upload_batches (id, s3_key, status) VALUES (:id, :key, :status)",
        id=batch_id,
        key=f"uploads/{batch_id}.csv",
        status=status,
    )
    return batch_id


def new_run(conn: Any, batch_id: uuid.UUID) -> int:
    rows = conn.run(
        "INSERT INTO pipeline_runs (batch_id, total_pairs) VALUES (:id, 0) RETURNING id",
        id=batch_id,
    )
    return int(rows[0][0])


def add_user(
    conn: Any,
    batch_id: uuid.UUID,
    income: int,
    score: int,
    age: int = 30,
    employment: str = "Salaried",
) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn.run(
        "INSERT INTO users (user_id, name, email, monthly_income, credit_score,"
        " employment_status, age, batch_id) VALUES (:id, 'T', 't@example.invalid', :income,"
        " :score, :employment, :age, :batch)",
        id=user_id,
        income=Decimal(income),
        score=score,
        employment=employment,
        age=age,
        batch=batch_id,
    )
    return user_id


def add_product(conn: Any, name: str, active: bool = True, **criteria: Any) -> int:
    columns = ["source", "product_name", "active", *criteria]
    values = [":source", ":name", ":active", *(f":{c}" for c in criteria)]
    rows = conn.run(
        f"INSERT INTO loan_products ({', '.join(columns)}) VALUES ({', '.join(values)})"
        " RETURNING id",
        source="test",
        name=name,
        active=active,
        **criteria,
    )
    return int(rows[0][0])


def single_row(conn: Any, rows: list[list[Any]]) -> dict[str, Any]:
    assert len(rows) == 1
    return dict(zip([c["name"] for c in conn.columns], rows[0], strict=True))


def run_stage1(conn: Any, run_id: int, batch_id: uuid.UUID) -> dict[str, Any]:
    """Run the pre-filter node, then the record node fed with its output, as n8n chains them."""
    params = {"run_id": str(run_id), "batch_id": batch_id}
    filtered = single_row(conn, conn.run(node_query(STAGE1_NODE, STAGE1_PARAMS), **params))
    recorded = single_row(
        conn,
        conn.run(
            node_query(RECORD_NODE, RECORD_PARAMS),
            **params,
            started_at=filtered["stage1_started_at"],
        ),
    )
    assert (recorded["run_id"], recorded["batch_id"]) == (str(run_id), str(batch_id))
    return {**filtered, **recorded}


def candidates(conn: Any, run_id: int) -> dict[tuple[uuid.UUID, int], list[str]]:
    rows = conn.run(
        "SELECT user_id, product_id, near_miss_criteria FROM match_candidates WHERE run_id = :r",
        r=run_id,
    )
    return {(u, p): sorted(c) for u, p, c in rows}


def test_every_criterion_boundary_and_near_miss_tag(connect_db: Callable[[], Any]) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    product = add_product(
        conn,
        "Bounded",
        min_monthly_income=Decimal(30000),
        min_credit_score=700,
        max_credit_score=749,
        min_age=21,
        max_age=60,
        allowed_employment=["Salaried", "Self-Employed"],
    )
    cases: dict[str, tuple[dict[str, Any], str | list[str]]] = {
        "at every floor": ({"income": 30000, "score": 700, "age": 21}, STRICT),
        "at every ceiling": ({"income": 30000, "score": 749, "age": 60}, STRICT),
        "income 95% of floor": ({"income": 28500, "score": 720}, ["min_monthly_income"]),
        "income below margin": ({"income": 28499, "score": 720}, EXCLUDED),
        "score 95% of floor": ({"income": 40000, "score": 665}, ["min_credit_score"]),
        "score below margin": ({"income": 40000, "score": 664}, EXCLUDED),
        "score within 5% above ceiling": ({"income": 40000, "score": 786}, ["max_credit_score"]),
        "score beyond ceiling margin": ({"income": 40000, "score": 787}, EXCLUDED),
        "two near misses": (
            {"income": 29000, "score": 690},
            ["min_credit_score", "min_monthly_income"],
        ),
        "age below floor": ({"income": 40000, "score": 720, "age": 20}, EXCLUDED),
        "age above ceiling": ({"income": 40000, "score": 720, "age": 61}, EXCLUDED),
        "employment not allowed": (
            {"income": 40000, "score": 720, "employment": "Business"},
            EXCLUDED,
        ),
        "second allowed employment": (
            {"income": 40000, "score": 720, "employment": "Self-Employed"},
            STRICT,
        ),
    }
    users = {label: add_user(conn, batch_id, **fields) for label, (fields, _) in cases.items()}

    result = run_stage1(conn, run_id, batch_id)
    found = candidates(conn, run_id)

    for label, (_, expected) in cases.items():
        key = (users[label], product)
        if expected == EXCLUDED:
            assert key not in found, label
        elif expected == STRICT:
            assert found[key] == [], label
        else:
            assert found[key] == expected, label
    near = sum(1 for _, e in cases.values() if isinstance(e, list))
    kept = sum(1 for _, e in cases.values() if e != EXCLUDED)
    assert (result["stage1_pairs"], result["stage1_near_miss"]) == (kept, near)
    assert result["stage1_strict"] == kept - near


def test_null_criteria_are_unconstrained_and_scope_is_batch_and_active(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    other_batch = new_batch(conn, status="processed")
    run_id = new_run(conn, batch_id)
    open_product = add_product(conn, "No criteria")
    add_product(conn, "Switched off", active=False)
    mine = [
        add_user(conn, batch_id, 1000, 300, age=18, employment="Business"),
        add_user(conn, batch_id, 500000, 900, age=100, employment="Self-Employed"),
    ]
    add_user(conn, other_batch, 50000, 750)

    result = run_stage1(conn, run_id, batch_id)

    assert candidates(conn, run_id) == {(u, open_product): [] for u in mine}
    assert (result["stage1_pairs"], result["stage1_near_miss"]) == (2, 0)


def test_rerun_is_idempotent_and_records_the_funnel(connect_db: Callable[[], Any]) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    add_product(conn, "Floor", min_credit_score=700)
    add_user(conn, batch_id, 40000, 720)
    add_user(conn, batch_id, 40000, 680)
    add_user(conn, batch_id, 40000, 600)

    first = run_stage1(conn, run_id, batch_id)
    second = run_stage1(conn, run_id, batch_id)

    assert (first["inserted_now"], second["inserted_now"]) == (2, 0)
    assert (second["stage1_pairs"], second["stage1_near_miss"]) == (2, 1)
    stored = conn.run(
        "SELECT stage1_pairs, stage1_near_miss, stage_ms ? 'stage1', (stage_ms->>'stage1')::int"
        " FROM pipeline_runs WHERE id = :id",
        id=run_id,
    )
    pairs, near, has_timing, ms = stored[0]
    assert (pairs, near, has_timing) == (2, 1, True)
    assert ms >= 0

    an_hour_ago = conn.run("SELECT now() - interval '1 hour'")[0][0]
    late_retry = conn.run(
        node_query(RECORD_NODE, RECORD_PARAMS),
        run_id=str(run_id),
        batch_id=batch_id,
        started_at=an_hour_ago,
    )
    assert late_retry[0][-1] == ms


def test_failure_branch_fails_only_a_matching_batch(connect_db: Callable[[], Any]) -> None:
    conn = connect_db()
    fail = node_query(FAIL_NODE, FAIL_PARAMS)
    matching = new_batch(conn)
    matching_run = new_run(conn, matching)
    matched = new_batch(conn, status="matched")
    matched_run = new_run(conn, matched)

    closed = conn.run(fail, run_id=str(matching_run), batch_id=matching, message="boom")
    untouched = conn.run(fail, run_id=str(matched_run), batch_id=matched, message="boom")

    assert closed == [[str(matching_run), str(matching)]]
    assert untouched == []
    states = conn.run(
        "SELECT b.status, b.error, r.finished_at IS NOT NULL FROM upload_batches b"
        " JOIN pipeline_runs r ON r.batch_id = b.id ORDER BY b.status DESC",
    )
    assert states == [["matched", None, False], ["failed", "matching stage 1 failed: boom", True]]
