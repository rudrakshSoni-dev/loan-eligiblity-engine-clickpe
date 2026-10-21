"""Workflow B Stage 3 on real PostgreSQL 16: the exported cohort SQL and Code nodes, chained as n8n
chains them, with Groq replaced by fake replies shaped like real ones.

Stages 1 and 2 run first with their own exported nodes, so the borderline pairs Stage 3 sees are
the ones the workflow would produce. Each request goes through the exported LLM Gateway nodes
(`run_gateway`), so `Stage 3 · Read verdicts` is fed exactly what the gateway returns.
"""

import hashlib
import json
import os
import re
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from pg8000.exceptions import DatabaseError

from tests.workflow_b_helpers import (
    NODE_BINARY,
    RUN_PARAMS,
    add_product,
    add_user,
    new_batch,
    new_run,
    node_query,
    run_code_node,
    run_stage1,
    run_stage2,
    single_row,
    workflow_node,
)
from tests.workflow_gateway_helpers import gateway_request, prepare, run_gateway, status_reply

pytestmark = [
    pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set"),
    pytest.mark.skipif(NODE_BINARY is None, reason="node not installed"),
]

FORM_NODE = "Stage 3 · Form cohorts"
BUILD_NODE = "Stage 3 · Build LLM requests"
READ_NODE = "Stage 3 · Read verdicts"
STORE_NODE = "Stage 3 · Store verdicts + fan out"
RECORD_NODE = "Record · Stage 3 funnel"
FAIL_NODE = "Fail · Mark batch failed (Stage 3)"
STORE_PARAMS = {"$1": ":run_id", "$2": ":batch_id", "$3": ":verdicts", "$4": ":unresolved"}
RECORD_PARAMS = {
    "$1": ":run_id",
    "$2": ":batch_id",
    "$3": ":started_at",
    "$4": ":cohorts",
    "$5": ":cache_hits",
    "$6": ":calls",
    "$7": ":tokens",
}
FAIL_PARAMS = {"$1": ":run_id", "$2": ":batch_id", "$3": ":message"}

MODEL = "openai/gpt-oss-120b"
SOFT_TEXT = "A credit score of 700 and above is preferred. Minimum monthly income of ₹30,000."

Reply = Callable[[dict[str, Any]], dict[str, Any]]


def js_constant(name: str) -> int:
    code = workflow_node(BUILD_NODE)["parameters"]["jsCode"]
    found = re.search(rf"const {name} = (\d+);", code)
    assert found is not None
    return int(found.group(1))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def soft_product(conn: Any, name: str = "Soft", text: str = SOFT_TEXT, **criteria: Any) -> int:
    defaults: dict[str, Any] = {"min_monthly_income": Decimal(30000), "min_credit_score": 700}
    return add_product(
        conn,
        name,
        parse_confidence=0.6,
        raw_criteria_text=text,
        content_hash=sha256(text),
        **{**defaults, **criteria},
    )


def only_item(output: list[dict[str, Any]]) -> dict[str, Any]:
    assert len(output) == 1
    item: dict[str, Any] = output[0]["json"]
    return item


def eligible_unless_income(cohort_key: str) -> bool:
    return "monthly income" not in cohort_key


def groq_reply(
    request: dict[str, Any],
    decide: Callable[[str], bool] = eligible_unless_income,
    tokens: tuple[int, int] = (120, 60),
) -> dict[str, Any]:
    verdicts = [
        {"cohort_id": c["cohort_id"], "eligible": decide(c["cohort_key"]), "reason": "quoted"}
        for c in request["cohorts"]
    ]
    return {
        "statusCode": 200,
        "headers": {},
        "body": {
            "model": MODEL,
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({"verdicts": verdicts})},
                }
            ],
            "usage": {
                "prompt_tokens": tokens[0],
                "completion_tokens": tokens[1],
                "total_time": 0.4,
            },
        },
    }


def through_gateway(request: dict[str, Any], reply: Reply) -> dict[str, Any]:
    """What `LLM · Judge cohorts (LLM Gateway)` returns for a request when Groq answers `reply`."""
    llm = gateway_request(**request["llm"], batch_id=request["batch_id"], run_id=request["run_id"])
    return run_gateway(llm, lambda _: reply(request)).result


def form(conn: Any, run_id: int, batch_id: uuid.UUID) -> dict[str, Any]:
    params = {"run_id": str(run_id), "batch_id": batch_id}
    return single_row(conn, conn.run(node_query(FORM_NODE, RUN_PARAMS), **params))


def read(built: dict[str, Any], responses: list[dict[str, Any]]) -> dict[str, Any]:
    items = responses if built["requests"] else [built]
    return only_item(run_code_node(READ_NODE, items, {BUILD_NODE: [built]}))


def store(conn: Any, item: dict[str, Any]) -> dict[str, Any]:
    rows = conn.run(
        node_query(STORE_NODE, STORE_PARAMS),
        run_id=item["run_id"],
        batch_id=uuid.UUID(item["batch_id"]),
        verdicts=json.dumps(item["verdicts"]),
        unresolved=json.dumps(item["unresolved"]),
    )
    return single_row(conn, rows)


def record(conn: Any, item: dict[str, Any]) -> dict[str, Any]:
    rows = conn.run(
        node_query(RECORD_NODE, RECORD_PARAMS),
        run_id=item["run_id"],
        batch_id=uuid.UUID(item["batch_id"]),
        started_at=item["stage3_started_at"],
        cohorts=item["cohort_count"],
        cache_hits=item["cache_hits"],
        calls=item["llm_calls"],
        tokens=item["llm_tokens"],
    )
    return single_row(conn, rows)


def run_stage3(
    conn: Any, run_id: int, batch_id: uuid.UUID, reply: Reply | None = None
) -> dict[str, Any]:
    """Chain the Stage 3 nodes as n8n does; `reply` stands in for Groq, one call per request."""
    built = only_item(run_code_node(BUILD_NODE, form(conn, run_id, batch_id)))
    responses = [through_gateway(r, reply) for r in built["requests"]] if reply else []
    assert len(responses) == len(built["requests"])
    item = read(built, responses)
    return {"built": built, "read": item, **store(conn, item), **record(conn, item)}


def funnel_to_borderline(conn: Any, run_id: int, batch_id: uuid.UUID) -> None:
    run_stage1(conn, run_id, batch_id)
    run_stage2(conn, run_id, batch_id)


def pair_outcomes(conn: Any, run_id: int) -> dict[tuple[uuid.UUID, int], tuple[Any, ...]]:
    rows = conn.run(
        "SELECT user_id, product_id, cohort_key, stage3_outcome, stage3_reason"
        " FROM match_candidates WHERE run_id = :r AND stage2_class = 'borderline'",
        r=run_id,
    )
    return {(r[0], r[1]): tuple(r[2:]) for r in rows}


def synthetic_cohort(product_id: int, n: int, **extra: Any) -> dict[str, Any]:
    return {
        "cohort_key": f"v1|product {product_id}|near_miss:min_credit_score|Salaried|band {n}",
        "product_id": product_id,
        "content_hash": "a" * 64,
        "borderline_reason": "near_miss:min_credit_score",
        "employment_status": "Salaried",
        "shortfalls": [
            {
                "feature": "credit_score",
                "bound": "minimum",
                "threshold": 700,
                "band_low": 690,
                "band_high": 699,
                "worst_value": 690,
            }
        ],
        "members": 3,
        "cached": False,
        **extra,
    }


def synthetic_form(cohorts: list[dict[str, Any]], usage: dict[str, Any]) -> dict[str, Any]:
    products = sorted({c["product_id"] for c in cohorts})
    return {
        "run_id": "7",
        "batch_id": str(uuid.uuid4()),
        "stage3_started_at": "2026-10-21 12:00:00+00",
        "cohorts": cohorts,
        "products": [
            {"product_id": p, "source": f"Lender {p}", "product_name": "PL", "criteria_text": "T"}
            for p in products
        ],
        "llm_usage_24h": usage,
    }


def test_cohorts_have_banded_keys_worst_values_and_label_their_pairs(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    soft = soft_product(conn)
    ceiling = soft_product(
        conn,
        "Ceiling",
        text="Scores up to 750.",
        min_monthly_income=None,
        min_credit_score=None,
        max_credit_score=750,
    )
    a = add_user(conn, batch_id, 60000, 690)
    b = add_user(conn, batch_id, 45000, 699)
    c = add_user(conn, batch_id, 60000, 689)
    d = add_user(conn, batch_id, 60000, 690, employment="Self-Employed")
    e = add_user(conn, batch_id, 29000, 740)
    f = add_user(conn, batch_id, 29999, 690)
    g = add_user(conn, batch_id, 60000, 760)
    funnel_to_borderline(conn, run_id, batch_id)

    formed = form(conn, run_id, batch_id)
    cohorts = {x["cohort_key"]: x for x in formed["cohorts"]}

    prefix = f"v1|product {soft}|near_miss:"
    expected_keys = {
        f"{prefix}min_credit_score|Salaried|credit score 690-699 vs minimum 700": 2,
        f"{prefix}min_credit_score|Salaried|credit score 680-689 vs minimum 700": 1,
        f"{prefix}min_credit_score|Self-Employed|credit score 690-699 vs minimum 700": 1,
        f"{prefix}min_monthly_income|Salaried|monthly income 29000-29999 vs minimum 30000": 1,
        f"{prefix}min_credit_score+min_monthly_income|Salaried|credit score 690-699 vs minimum"
        " 700|monthly income 29000-29999 vs minimum 30000": 1,
        f"v1|product {ceiling}|near_miss:max_credit_score|Salaried|credit score 760-769 vs"
        " maximum 750": 1,
    }
    assert {k: v["members"] for k, v in cohorts.items()} == expected_keys
    ceiling_key = next(k for k in cohorts if "maximum" in k)
    assert cohorts[ceiling_key]["shortfalls"][0]["worst_value"] == 769
    both_key = next(k for k in cohorts if "+" in k)
    assert [s["worst_value"] for s in cohorts[both_key]["shortfalls"]] == [690, 29000]
    assert all(x["cached"] is False and x["content_hash"] for x in cohorts.values())
    assert formed["labelled_now"] == 7
    assert {p["product_id"] for p in formed["products"]} == {soft, ceiling}

    labelled = pair_outcomes(conn, run_id)
    assert {labelled[(u, soft)][0] for u in (a, b)} == {next(iter(expected_keys))}
    assert (c, soft) in labelled and (d, soft) in labelled and (e, soft) in labelled
    assert labelled[(f, soft)][0] == both_key and labelled[(g, ceiling)][0] == ceiling_key
    assert conn.run(
        "SELECT count(*) FROM match_candidates WHERE run_id = :r"
        " AND (cohort_key IS NULL) <> (stage2_class <> 'borderline')",
        r=run_id,
    ) == [[0]]
    assert form(conn, run_id, batch_id)["labelled_now"] == 0


def test_requests_are_packed_per_product_and_skip_cached_and_unhashed_cohorts() -> None:
    per_request = js_constant("MAX_COHORTS_PER_REQUEST")
    first = [synthetic_cohort(1, n) for n in range(per_request + 1)]
    cached = synthetic_cohort(2, 90, cached=True)
    unhashed = synthetic_cohort(2, 91, content_hash=None)
    second = [synthetic_cohort(2, 92), cached, unhashed]

    built = only_item(run_code_node(BUILD_NODE, synthetic_form(first + second, {})))

    requests = built["requests"]
    assert [(r["request_no"], r["product_id"], len(r["cohorts"])) for r in requests] == [
        (1, 1, per_request),
        (2, 1, 1),
        (3, 2, 1),
    ]
    ids = [c["cohort_id"] for c in requests[0]["cohorts"]]
    assert ids[:2] == ["c01", "c02"] and len(set(ids)) == per_request
    llm = requests[0]["llm"]
    assert (llm["purpose"], llm["model"], llm["schema_name"]) == (
        "cohort_verdict",
        MODEL,
        "cohort_verdicts",
    )
    verdict = llm["json_schema"]["properties"]["verdicts"]["items"]
    assert verdict["properties"]["cohort_id"]["enum"] == ids
    assert (
        llm["max_tokens"]
        == js_constant("COMPLETION_TOKENS_BASE")
        + js_constant("COMPLETION_TOKENS_PER_COHORT") * per_request
    )
    user = requests[2]["llm"]["user"]
    assert user.count("Lender eligibility text:") == 1
    line = "c01: Salaried applicants; credit score 690 to 699, below the lender's figure of 700"
    assert line in user
    assert "(worst value 690)" in user
    assert all(r["run_id"] == "7" and r["estimated_tokens"] > 0 for r in requests)
    accepted = prepare(gateway_request(**llm, batch_id=built["batch_id"], run_id=7), {"usage": {}})
    assert (accepted["next"], accepted["estimated_tokens"]) == (
        "call",
        requests[0]["estimated_tokens"],
    )
    assert (built["cohort_count"], built["cache_hits"]) == (len(first) + 3, 1)
    assert [(u["cohort_key"], u["outcome"]) for u in built["unresolved"]] == [
        (unhashed["cohort_key"], "unresolved_error")
    ]


def test_budget_guard_sends_only_what_fits_and_counts_only_its_own_model() -> None:
    daily = js_constant("DAILY_TOKEN_BUDGET")
    cohorts = [synthetic_cohort(1, 1), synthetic_cohort(2, 2)]
    probe = only_item(run_code_node(BUILD_NODE, synthetic_form(cohorts, {})))
    first_cost = probe["requests"][0]["estimated_tokens"]

    def built_with(used: int) -> dict[str, Any]:
        usage = {MODEL: {"tokens": used, "calls": 5}, "openai/gpt-oss-20b": {"tokens": daily}}
        return only_item(run_code_node(BUILD_NODE, synthetic_form(cohorts, usage)))

    exactly = built_with(daily - first_cost)
    over = built_with(daily - first_cost + 1)

    assert [r["product_id"] for r in exactly["requests"]] == [1]
    assert [u["outcome"] for u in exactly["unresolved"]] == ["unresolved_budget"]
    assert "has 0 of" in exactly["unresolved"][0]["reason"]
    assert over["requests"] == []
    assert len(over["unresolved"]) == 2
    assert f"has {first_cost - 1} of {daily} tokens left" in over["unresolved"][0]["reason"]
    assert exactly["budget"]["used_tokens_24h"] == daily - first_cost


def test_budget_guard_caps_calls_per_run() -> None:
    cap = js_constant("MAX_CALLS_PER_RUN")
    cohorts = [synthetic_cohort(p, p) for p in range(1, cap + 2)]

    built = only_item(run_code_node(BUILD_NODE, synthetic_form(cohorts, {})))

    assert len(built["requests"]) == cap
    assert [u["outcome"] for u in built["unresolved"]] == ["unresolved_budget"]
    assert f"maximum of {cap} LLM calls" in built["unresolved"][0]["reason"]


def test_read_accepts_only_one_well_formed_verdict_per_cohort() -> None:
    cohorts = [synthetic_cohort(1, n) for n in range(5)]
    built = only_item(run_code_node(BUILD_NODE, synthetic_form(cohorts, {})))
    answers = [
        {"cohort_id": "c01", "eligible": True, "reason": "  preferred  "},
        {"cohort_id": "c02", "eligible": True, "reason": "a"},
        {"cohort_id": "c02", "eligible": False, "reason": "b"},
        {"cohort_id": "c03", "eligible": "yes", "reason": "c"},
        {"cohort_id": "c04", "eligible": False, "reason": "x" * 400},
        {"cohort_id": "c99", "eligible": True, "reason": "not asked"},
    ]
    answer = {
        "ok": True,
        "data": {"verdicts": answers},
        "model": MODEL,
        "tokens": 180,
        "attempts": 1,
    }

    item = read(built, [answer])

    keys = [c["cohort_key"] for c in built["requests"][0]["cohorts"]]
    assert [(v["cohort_key"], v["eligible"], v["model"]) for v in item["verdicts"]] == [
        (keys[0], True, MODEL),
        (keys[3], False, MODEL),
    ]
    assert item["verdicts"][0]["reason"] == "preferred"
    assert len(item["verdicts"][1]["reason"]) == 300
    reasons = {u["cohort_key"]: u["reason"] for u in item["unresolved"]}
    assert set(reasons) == {keys[1], keys[2], keys[4]}
    assert "2 verdicts" in reasons[keys[1]]
    assert "no well-formed verdict" in reasons[keys[2]] and "no well-formed" in reasons[keys[4]]
    assert (item["llm_calls"], item["llm_tokens"]) == (1, 180)


def content_reply(content: str) -> dict[str, Any]:
    return {
        "statusCode": 200,
        "body": {"choices": [{"finish_reason": "stop", "message": {"content": content}}]},
    }


@pytest.mark.parametrize(
    ("reply", "expected", "attempts"),
    [
        (
            status_reply(429, "21", "TPM limit 8000"),
            "Groq rate limited (HTTP 429) on openai/gpt-oss-20b after 6 waits, retry-after 21 s:"
            " TPM limit 8000",
            8,
        ),
        (status_reply(500, message="boom"), "Groq HTTP 500: boom", 2),
        ({"error": {"message": "ECONNRESET"}}, "No response from Groq: ECONNRESET", 1),
        (content_reply("{not json"), "Groq answer rejected: the message content is not JSON", 1),
        ({"statusCode": 200, "body": {}}, "the reply has no choices", 1),
        (content_reply("{}"), "it does not match the schema: $.verdicts is missing", 1),
        (
            content_reply('{"verdicts": [{"cohort_id": "c99", "eligible": true, "reason": "x"}]}'),
            "$.verdicts[0].cohort_id is not one of the allowed values",
            1,
        ),
    ],
)
def test_failed_calls_leave_every_cohort_unresolved_with_the_reason(
    reply: dict[str, Any], expected: str, attempts: int
) -> None:
    cohorts = [synthetic_cohort(1, n) for n in range(2)]
    built = only_item(run_code_node(BUILD_NODE, synthetic_form(cohorts, {})))

    item = read(built, [through_gateway(built["requests"][0], lambda _: reply)])

    assert item["verdicts"] == []
    assert [u["outcome"] for u in item["unresolved"]] == ["unresolved_error"] * 2
    assert all(expected in u["reason"] for u in item["unresolved"])
    assert (item["llm_calls"], item["llm_tokens"]) == (attempts, 0)


def test_a_gateway_budget_refusal_is_unresolved_budget_and_costs_no_call() -> None:
    cohorts = [synthetic_cohort(1, n) for n in range(2)]
    built = only_item(run_code_node(BUILD_NODE, synthetic_form(cohorts, {})))
    request = built["requests"][0]
    spent = {
        MODEL: {"tokens": 0, "calls": 10_000},
        "openai/gpt-oss-20b": {"tokens": 0, "calls": 10_000},
    }
    llm = gateway_request(**request["llm"], batch_id=request["batch_id"], run_id=request["run_id"])

    item = read(built, [run_gateway(llm, [], spent).result])

    assert [u["outcome"] for u in item["unresolved"]] == ["unresolved_budget"] * 2
    assert "daily budget" in item["unresolved"][0]["reason"]
    assert (item["llm_calls"], item["llm_tokens"]) == (0, 0)


def test_a_failed_gateway_execution_is_unresolved_error_with_its_message() -> None:
    cohorts = [synthetic_cohort(1, n) for n in range(2)]
    built = only_item(run_code_node(BUILD_NODE, synthetic_form(cohorts, {})))

    item = read(built, [{"error": "Workflow is not active and cannot be executed"}])

    assert [u["outcome"] for u in item["unresolved"]] == ["unresolved_error"] * 2
    assert "LLM Gateway failed: Workflow is not active" in item["unresolved"][0]["reason"]
    assert item["llm_calls"] == 0


def test_verdicts_fan_out_to_every_member_and_the_funnel_is_recorded(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    soft = soft_product(conn)
    score_a = add_user(conn, batch_id, 60000, 690)
    score_b = add_user(conn, batch_id, 45000, 695)
    income = add_user(conn, batch_id, 29000, 740)
    both = add_user(conn, batch_id, 29500, 690)
    add_user(conn, batch_id, 60000, 760)
    funnel_to_borderline(conn, run_id, batch_id)

    result = run_stage3(conn, run_id, batch_id, groq_reply)

    found = pair_outcomes(conn, run_id)
    assert found[(score_a, soft)][1:] == ("eligible", "quoted")
    assert found[(score_a, soft)][0] == found[(score_b, soft)][0]
    assert found[(score_b, soft)][1] == "eligible"
    assert found[(income, soft)][1] == found[(both, soft)][1] == "not_eligible"
    assert conn.run(
        "SELECT count(*), bool_and(model = :m), bool_and(product_content_hash = :h)"
        " FROM cohort_verdicts",
        m=MODEL,
        h=sha256(SOFT_TEXT),
    ) == [[3, True, True]]
    assert (result["verdicts_stored"], result["pairs_updated"]) == (3, 4)
    assert (result["llm_cohorts"], result["cache_hits"], result["llm_calls"]) == (3, 0, 1)
    assert result["llm_tokens"] == 180
    assert (result["stage3_eligible"], result["stage3_not_eligible"]) == (2, 2)
    assert (result["unresolved_budget"], result["unresolved_error"]) == (0, 0)
    assert result["stage2_borderline"] == 4 and result["stage3_ms"] >= 0


def test_cache_serves_a_later_batch_until_the_product_text_changes(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    soft = soft_product(conn)
    first_batch = new_batch(conn)
    first_run = new_run(conn, first_batch)
    add_user(conn, first_batch, 60000, 690)
    add_user(conn, first_batch, 29000, 740)
    funnel_to_borderline(conn, first_run, first_batch)
    run_stage3(conn, first_run, first_batch, groq_reply)

    second_batch = new_batch(conn)
    second_run = new_run(conn, second_batch)
    newcomer = add_user(conn, second_batch, 52000, 694)
    add_user(conn, second_batch, 29400, 760)
    funnel_to_borderline(conn, second_run, second_batch)
    cached = run_stage3(conn, second_run, second_batch, reply=None)

    assert cached["built"]["requests"] == []
    assert (cached["llm_cohorts"], cached["cache_hits"], cached["llm_calls"]) == (2, 2, 0)
    assert (cached["llm_tokens"], cached["verdicts_stored"]) == (0, 0)
    assert pair_outcomes(conn, second_run)[(newcomer, soft)][1] == "eligible"

    changed = "A credit score of 700 and above is required."
    conn.run(
        "UPDATE loan_products SET raw_criteria_text = :t, content_hash = :h WHERE id = :id",
        t=changed,
        h=sha256(changed),
        id=soft,
    )
    third_batch = new_batch(conn)
    third_run = new_run(conn, third_batch)
    add_user(conn, third_batch, 60000, 690)
    funnel_to_borderline(conn, third_run, third_batch)
    rejudged = run_stage3(conn, third_run, third_batch, lambda r: groq_reply(r, lambda _: False))

    assert (rejudged["cache_hits"], rejudged["llm_calls"], rejudged["stage3_not_eligible"]) == (
        0,
        1,
        1,
    )
    asked = rejudged["built"]["requests"][0]["llm"]["user"]
    assert changed in asked


def test_rerun_of_the_same_run_changes_nothing_and_keeps_first_measurements(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    soft_product(conn)
    add_user(conn, batch_id, 60000, 690)
    funnel_to_borderline(conn, run_id, batch_id)
    first = run_stage3(conn, run_id, batch_id, groq_reply)
    before = pair_outcomes(conn, run_id)

    second = run_stage3(conn, run_id, batch_id, reply=None)

    assert (second["verdicts_stored"], second["pairs_updated"]) == (0, 0)
    assert pair_outcomes(conn, run_id) == before
    kept = ("llm_cohorts", "cache_hits", "llm_calls", "llm_tokens", "stage3_ms")
    assert {k: second[k] for k in kept} == {k: first[k] for k in kept}


def test_unresolved_pairs_are_counted_never_guessed_and_resolve_on_a_later_call(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    soft = soft_product(conn)
    user = add_user(conn, batch_id, 60000, 690)
    funnel_to_borderline(conn, run_id, batch_id)

    def rate_limited(_: dict[str, Any]) -> dict[str, Any]:
        return {"statusCode": 429, "headers": {"retry-after": "9"}, "body": {}}

    limited = run_stage3(conn, run_id, batch_id, rate_limited)

    assert (limited["unresolved_error"], limited["stage3_eligible"]) == (1, 0)
    assert pair_outcomes(conn, run_id)[(user, soft)][1] == "unresolved_error"
    assert "retry-after 9 s" in pair_outcomes(conn, run_id)[(user, soft)][2]
    assert conn.run("SELECT count(*) FROM cohort_verdicts") == [[0]]

    resolved = run_stage3(conn, run_id, batch_id, groq_reply)

    assert (resolved["unresolved_error"], resolved["stage3_eligible"]) == (0, 1)
    assert resolved["pairs_updated"] == 1


def test_budget_skipped_cohorts_are_recorded_as_unresolved_budget(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    soft_product(conn)
    add_user(conn, batch_id, 60000, 690)
    add_user(conn, batch_id, 61000, 691)
    funnel_to_borderline(conn, run_id, batch_id)
    conn.run(
        "INSERT INTO llm_calls (purpose, model, prompt_tokens, completion_tokens, status)"
        " VALUES ('crawl_structuring', :m, :t, 0, 200)",
        m=MODEL,
        t=js_constant("DAILY_TOKEN_BUDGET"),
    )

    result = run_stage3(conn, run_id, batch_id, reply=None)

    assert (result["unresolved_budget"], result["llm_calls"], result["llm_tokens"]) == (2, 0, 0)
    reasons = {r[2] for r in pair_outcomes(conn, run_id).values()}
    assert len(reasons) == 1 and "daily Stage 3 token budget has 0 of" in reasons.pop()


def test_record_refuses_a_run_whose_pairs_were_not_fanned_out(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    soft_product(conn)
    add_user(conn, batch_id, 60000, 690)
    funnel_to_borderline(conn, run_id, batch_id)
    built = only_item(run_code_node(BUILD_NODE, form(conn, run_id, batch_id)))
    item = read(built, [groq_reply(r) for r in built["requests"]])

    with pytest.raises(DatabaseError, match="pipeline_runs_check"):
        record(conn, item)

    assert conn.run("SELECT stage3_eligible FROM pipeline_runs WHERE id = :id", id=run_id) == [
        [None]
    ]


def test_run_with_no_borderline_pairs_records_measured_zeros(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    batch_id = new_batch(conn)
    run_id = new_run(conn, batch_id)
    soft_product(conn)
    add_user(conn, batch_id, 60000, 760)
    funnel_to_borderline(conn, run_id, batch_id)

    result = run_stage3(conn, run_id, batch_id, reply=None)

    assert result["built"]["requests"] == [] and result["read"]["unresolved"] == []
    counts = ("llm_cohorts", "cache_hits", "llm_calls", "llm_tokens", "stage3_eligible")
    assert {k: result[k] for k in counts} == dict.fromkeys(counts, 0)
    assert (result["stage3_not_eligible"], result["unresolved_error"]) == (0, 0)


def test_failure_branch_names_stage_3(connect_db: Callable[[], Any]) -> None:
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
    ) == [["failed", "matching stage 3 failed: boom", True]]
