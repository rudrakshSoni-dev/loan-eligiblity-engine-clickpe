"""Workflow A's change-detection wiring and its Code node, run under Node.js."""

import json
from typing import Any

import pytest

from tests.workflow_b_helpers import NODE_BINARY, run_code_node
from tests.workflow_gateway_helpers import WORKFLOWS_DIR

WORKFLOW_A = WORKFLOWS_DIR / "workflow-a-product-discovery.json"
NORMALIZE = "Normalize · Criteria lines"
CRITERIA_CHECK = "Check · Criteria found"
LOOKUP = "Lookup · Stored content hash"
TAG = "Tag · Content unchanged"
CHANGED_CHECK = "Check · Content changed"
PROMPT = "Prompt · Build LLM request"
TOUCH = "Touch · last_seen_at + crawl_runs (unchanged)"
TOUCH_FAILED = "Mark · Touch failed"
FAILURE_LOG = "Log · crawl_runs failure"
GATEWAY = "LLM · Structure criteria (LLM Gateway)"
PAGE = {
    "source": "ICICI Bank",
    "product_name": "Personal Loan",
    "source_url": "https://example.invalid/pl",
    "criteria_text": "Minimum net monthly income of ₹30,000",
}


def workflow() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(WORKFLOW_A.read_text(encoding="utf-8"))[0]
    return loaded


def targets(source: str) -> list[list[str]]:
    outputs = workflow()["connections"][source]["main"]
    return [[link["node"] for link in output] for output in outputs]


def node(name: str) -> dict[str, Any]:
    found: dict[str, Any] = next(n for n in workflow()["nodes"] if n["name"] == name)
    return found


def reachable(start: str) -> set[str]:
    seen: set[str] = set()
    pending = [start]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        for output in workflow()["connections"].get(current, {}).get("main", []):
            pending.extend(link["node"] for link in output)
    return seen


def test_a_page_with_criteria_is_looked_up_before_any_llm_step() -> None:
    assert targets(CRITERIA_CHECK)[0] == [LOOKUP]
    assert targets(LOOKUP) == [[TAG]]
    assert targets(TAG) == [[CHANGED_CHECK]]


def test_changed_pages_continue_to_the_llm_and_unchanged_pages_go_to_touch() -> None:
    assert targets(CHANGED_CHECK) == [[PROMPT], [TOUCH]]


def test_the_unchanged_path_cannot_reach_the_llm_gateway() -> None:
    assert GATEWAY not in reachable(TOUCH)
    assert GATEWAY in reachable(PROMPT)


def test_a_failed_touch_is_logged_and_does_not_stop_the_other_sites() -> None:
    assert targets(TOUCH) == [[], [TOUCH_FAILED]]
    assert node(TOUCH)["onError"] == "continueErrorOutput"
    assert targets(TOUCH_FAILED) == [[FAILURE_LOG]]


def test_a_failed_lookup_continues_on_the_regular_output() -> None:
    assert node(LOOKUP)["onError"] == "continueRegularOutput"


def test_lookup_and_touch_hash_with_the_same_postgres_function_as_the_upsert() -> None:
    upsert = node("Upsert · loan_products + crawl_runs")["parameters"]["query"]
    expression = "encode(sha256(convert_to("
    for name in (LOOKUP, TOUCH):
        assert expression in node(name)["parameters"]["query"]
    assert expression in upsert


def test_tag_runs_once_per_site_so_every_lookup_row_is_kept() -> None:
    assert node(TAG)["parameters"]["mode"] == "runOnceForEachItem"


def tag(lookup_output: dict[str, Any]) -> dict[str, Any]:
    output: Any = run_code_node(TAG, lookup_output, {NORMALIZE: [PAGE]}, WORKFLOW_A)
    item: dict[str, Any] = output["json"]
    return item


@pytest.mark.skipif(NODE_BINARY is None, reason="node not installed")
@pytest.mark.parametrize(
    ("lookup_output", "expected"),
    [
        ({"unchanged": True}, True),
        ({"unchanged": False}, False),
        ({"error": {"name": "NodeOperationError"}}, False),
        ({}, False),
        ({"unchanged": "true"}, False),
    ],
)
def test_tag_marks_only_a_strict_true_lookup_as_unchanged(
    lookup_output: dict[str, Any], expected: bool
) -> None:
    item = tag(lookup_output)
    assert item["content_unchanged"] is expected


@pytest.mark.skipif(NODE_BINARY is None, reason="node not installed")
def test_tag_keeps_the_page_fields_the_prompt_node_needs() -> None:
    item = tag({"unchanged": False})
    assert {key: item[key] for key in PAGE} == PAGE
