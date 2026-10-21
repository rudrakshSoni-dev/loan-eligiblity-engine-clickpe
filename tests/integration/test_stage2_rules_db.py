"""Workflow B Stage 2 on real PostgreSQL 16: the exported rule-card Code node runs under Node.js and
the exported SQL classifies the pairs Stage 1 left in `match_candidates`.

Expected EMIs are computed here with the standard amortisation formula, independently of the
JavaScript, so a wrong formula in the Code node fails a test.
"""

import json
import os
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from pg8000.exceptions import DatabaseError

from tests.workflow_b_helpers import (
    NODE_BINARY,
    add_product,
    add_user,
    new_batch,
    new_run,
    node_query,
    run_code_node,
    single_row,
)

pytestmark = [
    pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set"),
    pytest.mark.skipif(NODE_BINARY is None, reason="node not installed"),
]

STAGE1_NODE = "Stage 1 · SQL pre-filter"
STAGE1_RECORD_NODE = "Record · Stage 1 funnel"
LOAD_NODE = "Stage 2 · Load product rules"
CARDS_NODE = "Stage 2 · Build rule cards"
CLASSIFY_NODE = "Stage 2 · Classify pairs"
RECORD_NODE = "Record · Stage 2 funnel"
FAIL_NODE = "Fail · Mark batch failed (Stage 2)"
RUN_PARAMS = {"$1": ":run_id", "$2": ":batch_id"}
TIMED_PARAMS = {"$1": ":run_id", "$2": ":batch_id", "$3": ":started_at"}
CLASSIFY_PARAMS = {"$1": ":run_id", "$2": ":batch_id", "$3": ":cards", "$4": ":started_at"}
FAIL_PARAMS = {"$1": ":run_id", "$2": ":batch_id", "$3": ":message"}

LOAN_RUPEES = 500_000
TENURE_MONTHS = 60
AFFORDABILITY_CAP = 0.65


def amortised_emi(annual_rate_pct: float) -> float:
    monthly = annual_rate_pct / 1200
    growth = (1 + monthly) ** TENURE_MONTHS
    return round(LOAN_RUPEES * monthly * growth / (growth - 1), 2)


def run_stage1(conn: Any, run_id: int, batch_id: uuid.UUID) -> None:
    params = {"run_id": str(run_id), "batch_id": batch_id}
    started = single_row(conn, conn.run(node_query(STAGE1_NODE, RUN_PARAMS), **params))
    conn.run(
        node_query(STAGE1_RECORD_NODE, TIMED_PARAMS),
        **params,
        started_at=started["stage1_started_at"],
    )


def build_cards(conn: Any, run_id: int, batch_id: uuid.UUID) -> dict[str, Any]:
    params = {"run_id": str(run_id), "batch_id": batch_id}
    loaded = single_row(conn, conn.run(node_query(LOAD_NODE, RUN_PARAMS), **params))
    output = run_code_node(CARDS_NODE, loaded)
    assert len(output) == 1
    item: dict[str, Any] = output[0]["json"]
    return item


def classify_and_record(conn: Any, item: dict[str, Any], cards: list[Any]) -> dict[str, Any]:
    params = {"run_id": item["run_id"], "batch_id": uuid.UUID(item["batch_id"])}
    classified = single_row(
        conn,
        conn.run(
            node_query(CLASSIFY_NODE, CLASSIFY_PARAMS),
            **params,
            cards=json.dumps(cards),
            started_at=item["stage2_started_at"],
        ),
    )
    recorded = single_row(
        conn,
        conn.run(
            node_query(RECORD_NODE, TIMED_PARAMS),
            **params,
            started_at=classified["stage2_started_at"],
        ),
    )
    return {**classified, **recorded}


def run_stage2(conn: Any, run_id: int, batch_id: uuid.UUID) -> dict[str, Any]:
    """Chain the four Stage 2 nodes exactly as n8n does, each fed with the previous output."""
    item = build_cards(conn, run_id, batch_id)
    return {**classify_and_record(conn, item, item["cards"]), "cards": item["cards"]}


def outcomes(conn: Any, run_id: int) -> dict[tuple[uuid.UUID, int], dict[str, Any]]:
    rows = conn.run(
        "SELECT user_id, product_id, stage2_class, borderline_reason, trigger_feature,"
        " trigger_value, indicative_emi, stage2_reason FROM match_candidates WHERE run_id = :r",
        r=run_id,
    )
    keys = ["class", "reason_key", "feature", "value", "emi", "reason"]
    return {(r[0], r[1]): dict(zip(keys, r[2:], strict=True)) for r in rows}


def test_all_three_classes_with_reasons_and_cohort_fields(connect_db: Callable[[], Any]) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    soft = add_product(
        conn,
        "Soft",
        min_monthly_income=Decimal(30000),
        min_credit_score=700,
        parse_confidence=0.6,
    )
    firm = add_product(
        conn, "Firm", min_credit_score=710, interest_rate_min=Decimal("9.99"), parse_confidence=0.7
    )
    strict_user = add_user(conn, batch_id, 60000, 760)
    low_score = add_user(conn, batch_id, 60000, 690)
    low_income = add_user(conn, batch_id, 29000, 750)
    both_low = add_user(conn, batch_id, 29000, 690)
    run_stage1(conn, run_id, batch_id)

    result = run_stage2(conn, run_id, batch_id)
    found = outcomes(conn, run_id)

    assert found[(strict_user, soft)]["class"] == "clear_match"
    assert found[(strict_user, firm)]["class"] == "clear_match"
    assert found[(low_score, firm)]["class"] == "clear_reject"
    assert found[(both_low, firm)]["class"] == "clear_reject"
    cohort_fields = ("class", "reason_key", "feature", "value")
    assert {k: found[(low_score, soft)][k] for k in cohort_fields} == {
        "class": "borderline",
        "reason_key": "near_miss:min_credit_score",
        "feature": "credit_score",
        "value": Decimal(690),
    }
    assert (found[(low_income, soft)]["reason_key"], found[(low_income, soft)]["value"]) == (
        "near_miss:min_monthly_income",
        Decimal(29000),
    )
    assert (found[(both_low, soft)]["reason_key"], found[(both_low, soft)]["feature"]) == (
        "near_miss:min_credit_score+min_monthly_income",
        "credit_score",
    )
    assert (low_income, firm) in found and found[(low_income, firm)]["class"] == "clear_match"

    assert found[(strict_user, firm)]["emi"] == Decimal(str(amortised_emi(9.99)))
    assert "₹10,621" in found[(strict_user, firm)]["reason"]
    assert "within 65% of income" in found[(strict_user, firm)]["reason"]
    assert found[(strict_user, soft)]["emi"] is None
    assert "Affordability not checked" in found[(strict_user, soft)]["reason"]
    assert "parse confidence 0.60" in found[(strict_user, soft)]["reason"]
    assert "credit score 690 vs minimum 710" in found[(low_score, firm)]["reason"]
    assert "monthly income ₹29,000 vs minimum ₹30,000" in found[(both_low, soft)]["reason"]
    assert all(o["class"] != "borderline" or o["reason_key"] for o in found.values())

    classes = [o["class"] for o in found.values()]
    assert (result["stage2_clear"], result["stage2_borderline"], result["stage2_reject"]) == (
        classes.count("clear_match"),
        classes.count("borderline"),
        classes.count("clear_reject"),
    )
    assert (result["stage2_clear"], result["stage2_borderline"], result["stage2_reject"]) == (
        3,
        3,
        2,
    )
    assert result["stage1_pairs"] == len(found)


def test_unaffordable_emi_rejects_even_a_strict_pass(connect_db: Callable[[], Any]) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    expensive = add_product(
        conn,
        "Expensive",
        interest_rate_min=Decimal("9.99"),
        interest_rate_max=Decimal(40),
        parse_confidence=0.9,
    )
    emi = amortised_emi(40)
    affordable_floor = int(emi / AFFORDABILITY_CAP) + 1
    just_short = add_user(conn, batch_id, affordable_floor - 1, 750)
    just_enough = add_user(conn, batch_id, affordable_floor, 750)
    run_stage1(conn, run_id, batch_id)

    result = run_stage2(conn, run_id, batch_id)
    found = outcomes(conn, run_id)

    assert result["cards"][0]["indicative_emi"] == emi
    assert found[(just_short, expensive)]["class"] == "clear_reject"
    assert found[(just_short, expensive)]["reason"].startswith("Not affordable")
    assert "top published rate of 40% p.a." in found[(just_short, expensive)]["reason"]
    assert found[(just_enough, expensive)]["class"] == "clear_match"


def test_rule_cards_for_missing_rate_zero_rate_and_missing_confidence(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    no_rate = add_product(conn, "No rate", parse_confidence=0.95)
    free = add_product(conn, "Zero rate", interest_rate_min=Decimal(0), parse_confidence=0.95)
    unknown = add_product(conn, "Unknown confidence", min_credit_score=700)
    add_user(conn, batch_id, 40000, 690)
    run_stage1(conn, run_id, batch_id)

    cards = {c["product_id"]: c for c in build_cards(conn, run_id, batch_id)["cards"]}

    assert (cards[no_rate]["indicative_emi"], cards[no_rate]["near_miss_policy"]) == (
        None,
        "clear_reject",
    )
    assert cards[free]["indicative_emi"] == round(LOAN_RUPEES / TENURE_MONTHS, 2)
    assert (cards[unknown]["parse_confidence"], cards[unknown]["near_miss_policy"]) == (
        0,
        "borderline",
    )


def test_rerun_is_idempotent_and_keeps_the_first_timing(connect_db: Callable[[], Any]) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    add_product(conn, "Soft", min_credit_score=700, parse_confidence=0.6)
    add_user(conn, batch_id, 40000, 720)
    add_user(conn, batch_id, 40000, 680)
    run_stage1(conn, run_id, batch_id)

    first = run_stage2(conn, run_id, batch_id)
    before = outcomes(conn, run_id)
    second = run_stage2(conn, run_id, batch_id)

    assert (first["classified_now"], second["classified_now"]) == (2, 0)
    assert outcomes(conn, run_id) == before
    assert (second["stage2_clear"], second["stage2_borderline"], second["stage2_reject"]) == (
        1,
        1,
        0,
    )
    assert second["stage2_ms"] == first["stage2_ms"] >= 0


def test_a_pair_without_a_rule_card_fails_the_funnel_check(connect_db: Callable[[], Any]) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    kept = add_product(conn, "Kept", parse_confidence=0.9)
    add_product(conn, "Dropped", parse_confidence=0.9)
    add_user(conn, batch_id, 40000, 720)
    run_stage1(conn, run_id, batch_id)
    item = build_cards(conn, run_id, batch_id)

    with pytest.raises(DatabaseError, match="pipeline_runs_check"):
        classify_and_record(conn, item, [c for c in item["cards"] if c["product_id"] == kept])

    assert conn.run("SELECT stage2_clear FROM pipeline_runs WHERE id = :id", id=run_id) == [[None]]


def test_run_with_no_candidates_records_measured_zeros(connect_db: Callable[[], Any]) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    add_product(conn, "Unreachable", min_credit_score=900)
    add_user(conn, batch_id, 40000, 650)
    run_stage1(conn, run_id, batch_id)

    result = run_stage2(conn, run_id, batch_id)

    assert result["cards"] == []
    assert (result["stage1_pairs"], result["stage2_clear"], result["stage2_borderline"]) == (
        0,
        0,
        0,
    )
    assert result["stage2_reject"] == 0


def test_failure_branch_names_stage_2(connect_db: Callable[[], Any]) -> None:
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
    ) == [["failed", "matching stage 2 failed: boom", True]]


def test_confidence_exactly_at_the_cutoff_counts_as_fully_structured(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    at_cutoff = add_product(conn, "At cutoff", min_credit_score=710, parse_confidence=0.7)
    assert conn.run("SELECT parse_confidence < 0.7 FROM loan_products") == [[True]]
    add_user(conn, batch_id, 40000, 690)
    run_stage1(conn, run_id, batch_id)

    cards = build_cards(conn, run_id, batch_id)["cards"]

    assert [(c["product_id"], c["near_miss_policy"]) for c in cards] == [
        (at_cutoff, "clear_reject")
    ]
