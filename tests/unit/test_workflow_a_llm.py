"""Workflow A's LLM steps under Node.js: the request it sends the gateway and how it reads replies.

The checks that matter for matching stay in `Coerce · Validate product` (database ranges, numbers
grounded in the source text, completeness-based confidence); the gateway only guarantees the
answer's shape.
"""

from typing import Any

import pytest

from tests.workflow_b_helpers import NODE_BINARY, run_code_node
from tests.workflow_gateway_helpers import (
    PREPARE_NODE,
    PRIMARY,
    gateway_request,
    js_constant,
    ok_reply,
    run_gateway,
)
from tests.workflow_gateway_helpers import WORKFLOWS_DIR as GATEWAY_DIR

pytestmark = pytest.mark.skipif(NODE_BINARY is None, reason="node not installed")

WORKFLOW_A = GATEWAY_DIR / "workflow-a-product-discovery.json"
PROMPT_NODE = "Prompt · Build LLM request"
COERCE_NODE = "Coerce · Validate product"
CRITERIA = (
    "Minimum net monthly income of ₹30,000\n"
    "Credit score of 700 and above is preferred\n"
    "Age between 21 and 60 years\n"
    "Salaried individuals"
)
PAGE = {
    "source": "ICICI Bank",
    "product_name": "Personal Loan",
    "source_url": "https://example.invalid/pl",
    "role": "primary",
    "criteria_text": CRITERIA,
    "line_count": 4,
    "fetched_at": "2026-10-22T06:00:00Z",
}
ANSWER = {
    "min_monthly_income": 30000,
    "min_credit_score": 700,
    "max_credit_score": None,
    "min_age": 21,
    "max_age": 60,
    "interest_rate_min": None,
    "interest_rate_max": None,
    "allowed_employment": ["Salaried"],
    "has_conditional_criteria": False,
}


def prompt_item() -> dict[str, Any]:
    output = run_code_node(PROMPT_NODE, PAGE, workflow_file=WORKFLOW_A)
    assert len(output) == 1
    item: dict[str, Any] = output[0]["json"]
    return item


def coerce(result: dict[str, Any]) -> dict[str, Any]:
    output: Any = run_code_node(COERCE_NODE, result, {PROMPT_NODE: [prompt_item()]}, WORKFLOW_A)
    item: dict[str, Any] = output["json"]
    return item


def test_prompt_hands_the_gateway_a_request_it_accepts() -> None:
    item = prompt_item()
    llm = item["llm"]

    assert (llm["purpose"], llm["model"], llm["schema_name"]) == (
        "crawl_structuring",
        PRIMARY,
        "loan_product_criteria",
    )
    assert CRITERIA in llm["user"] and item["criteria_text"] == CRITERIA
    assert llm["json_schema"]["additionalProperties"] is False
    run = run_gateway(gateway_request(**llm), [ok_reply(ANSWER)])
    assert run.result["ok"] is True and run.result["data"] == ANSWER
    assert run.result["estimated_tokens"] <= js_constant(PREPARE_NODE, "TOKENS_PER_MINUTE_LIMIT")


def test_coerce_turns_a_gateway_answer_into_a_product_row() -> None:
    run = run_gateway(gateway_request(**prompt_item()["llm"]), [ok_reply(ANSWER, (900, 120))])

    row = coerce(run.result)

    assert row["status"] == "structured"
    assert (row["min_monthly_income"], row["min_credit_score"], row["min_age"]) == (30000, 700, 21)
    assert row["allowed_employment"] == ["Salaried"]
    assert (row["prompt_tokens"], row["completion_tokens"], row["llm_calls"]) == (900, 120, 1)
    assert row["model"] == PRIMARY and row["parse_confidence"] == 0.85


def test_coerce_still_rejects_numbers_that_are_not_in_the_text() -> None:
    invented = {**ANSWER, "min_monthly_income": 45000}
    run = run_gateway(gateway_request(**prompt_item()["llm"]), [ok_reply(invented)])

    row = coerce(run.result)

    assert row["status"] == "structuring_invalid"
    assert "min_monthly_income=45000 does not appear in the criteria text" in row["error"]
    assert '"min_monthly_income":45000' in row["raw_model_output"]


def test_coerce_rejects_an_answer_without_data() -> None:
    row = coerce({"ok": True, "data": None, "model": PRIMARY, "attempts": 1})

    assert row["status"] == "structuring_invalid"
    assert "LLM Gateway answer is not a JSON object" in row["error"]
