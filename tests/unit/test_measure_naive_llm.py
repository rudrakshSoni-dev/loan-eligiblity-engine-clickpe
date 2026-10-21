"""scripts/measure_naive_llm.py: prompt taken from Workflow B, request shape, averaging."""

from typing import Any

import pytest

from scripts.measure_naive_llm import (
    COHORT_ID,
    WORKFLOW_B,
    build_request,
    shortfall_text,
    stage3_system_prompt,
    summarise,
)

PAIR: dict[str, Any] = {
    "near_miss_criteria": ["min_credit_score", "min_monthly_income"],
    "employment_status": "Salaried",
    "credit_score": 712,
    "monthly_income": 24_000,
    "source": "Test Bank",
    "product_name": "Personal Loan",
    "criteria_text": "Minimum credit score 720.",
    "min_credit_score": 720,
    "max_credit_score": None,
    "min_monthly_income": 25_000,
}


def test_system_prompt_comes_from_the_exported_workflow() -> None:
    prompt = stage3_system_prompt(WORKFLOW_B)
    assert prompt.startswith("You review borderline personal-loan applicants")
    assert prompt.count("\n") == 8


def test_shortfall_names_every_near_miss_criterion() -> None:
    text = shortfall_text(PAIR)
    assert "credit score 712, below the lender's figure of 720" in text
    assert "Rs 24,000, below the lender's figure of Rs 25,000" in text


def test_maximum_score_shortfall_is_above_the_figure() -> None:
    pair = {**PAIR, "near_miss_criteria": ["max_credit_score"], "max_credit_score": 800}
    assert "above the lender's figure of 800" in shortfall_text(pair)


def test_request_asks_about_one_applicant_under_a_strict_schema() -> None:
    request = build_request(PAIR, "system")
    schema = request["response_format"]["json_schema"]
    item = schema["schema"]["properties"]["verdicts"]["items"]
    assert (schema["strict"], item["properties"]["cohort_id"]["enum"]) == (True, [COHORT_ID])
    assert request["messages"][1]["content"].endswith("applicants; " + shortfall_text(PAIR) + ".")


def test_summary_averages_the_calls() -> None:
    calls = [
        {"prompt_tokens": 1000, "completion_tokens": 100, "latency_ms": 400},
        {"prompt_tokens": 1200, "completion_tokens": 200, "latency_ms": 600},
    ]
    assert summarise(calls) == {
        "calls": 2,
        "mean_prompt_tokens": 1100,
        "mean_completion_tokens": 150,
        "mean_total_tokens": 1250,
        "mean_latency_ms": 500,
    }


def test_missing_prompt_is_an_error(tmp_path: Any) -> None:
    broken = tmp_path / "w.json"
    broken.write_text(
        '{"nodes":[{"name":"Stage 3 · Build LLM requests","parameters":{"jsCode":"x"}}]}'
    )
    with pytest.raises(ValueError, match="no SYSTEM_PROMPT"):
        stage3_system_prompt(broken)
