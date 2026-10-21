"""Static checks on the exported LLM Gateway and on how Workflows A and B call it.

The gateway is meant to be the only place that talks to Groq and writes `llm_calls`; these tests
fail if a workflow grows its own Groq request or ledger insert again, or if a caller stops passing
an input the gateway expects.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.workflow_e_helpers import WORKFLOW_E_ID
from tests.workflow_gateway_helpers import (
    ATTEMPT_NODE,
    BUDGET_NODE,
    CHECK_NODE,
    GATEWAY,
    GATEWAY_ID,
    HTTP_NODE,
    LOG_NODE,
    PREPARE_NODE,
    READ_NODE,
    RESTORE_NODE,
    RETURN_NODE,
    ROUTE_NODE,
    TRIGGER_NODE,
    WAIT_NODE,
    WORKFLOWS_DIR,
)

NODE_REFERENCE = re.compile(r"\$\('([^']+)'\)")
COMMENT_LINE = re.compile(r"^\s*(//|/\*|--)", re.MULTILINE)
GROQ_URL = "api.groq.com"
WORKFLOW_A = WORKFLOWS_DIR / "workflow-a-product-discovery.json"
WORKFLOW_B = WORKFLOWS_DIR / "workflow-b-matching.json"
CALLERS = {
    WORKFLOW_A: "LLM · Structure criteria (LLM Gateway)",
    WORKFLOW_B: "LLM · Judge cohorts (LLM Gateway)",
}
INPUTS = {
    "purpose": "string",
    "model": "string",
    "system": "string",
    "user": "string",
    "schema_name": "string",
    "json_schema": "object",
    "max_tokens": "number",
    "batch_id": "string",
    "run_id": "number",
}


def workflow(path: Path = GATEWAY) -> dict[str, Any]:
    exported: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))[0]
    return exported


def node(name: str, path: Path = GATEWAY) -> dict[str, Any]:
    found: dict[str, Any] = next(n for n in workflow(path)["nodes"] if n["name"] == name)
    return found


def targets(name: str, output: int = 0) -> list[str]:
    return [t["node"] for t in workflow()["connections"][name]["main"][output]]


def test_identity_settings_and_no_pinned_data() -> None:
    exported = workflow()
    nodes = exported["nodes"]
    assert exported["id"] == GATEWAY_ID
    assert exported["settings"]["errorWorkflow"] == WORKFLOW_E_ID
    assert exported["settings"]["executionOrder"] == "v1"
    assert exported["pinData"] == {}
    assert len({n["name"] for n in nodes}) == len(nodes)
    assert len({n["id"] for n in nodes}) == len(nodes)


def test_trigger_declares_typed_inputs() -> None:
    parameters = node(TRIGGER_NODE)["parameters"]
    assert parameters["inputSource"] == "workflowInputs"
    declared = {v["name"]: v["type"] for v in parameters["workflowInputs"]["values"]}
    assert declared == INPUTS


def test_main_path_and_retry_loop_are_wired() -> None:
    assert targets(TRIGGER_NODE) == [BUDGET_NODE]
    assert targets(BUDGET_NODE) == [PREPARE_NODE]
    assert targets(PREPARE_NODE) == [CHECK_NODE]
    assert targets(CHECK_NODE, 0) == [ATTEMPT_NODE]
    assert targets(CHECK_NODE, 1) == [RETURN_NODE]
    assert targets(ATTEMPT_NODE) == [HTTP_NODE]
    assert targets(HTTP_NODE) == [READ_NODE]
    assert targets(READ_NODE) == [LOG_NODE]
    assert targets(LOG_NODE) == [RESTORE_NODE]
    assert targets(RESTORE_NODE) == [ROUTE_NODE]
    assert targets(ROUTE_NODE, 0) == [WAIT_NODE]
    assert targets(ROUTE_NODE, 1) == [RETURN_NODE]
    assert targets(WAIT_NODE) == [ATTEMPT_NODE]
    assert RETURN_NODE not in workflow()["connections"]


def test_every_reference_and_connection_names_a_real_node() -> None:
    exported = workflow()
    names = {n["name"] for n in exported["nodes"]}
    referenced = {
        ref
        for n in exported["nodes"]
        for ref in NODE_REFERENCE.findall(json.dumps(n["parameters"], ensure_ascii=False))
    }
    assert {TRIGGER_NODE, ATTEMPT_NODE, READ_NODE} <= referenced <= names
    linked = {
        t["node"]
        for outputs in exported["connections"].values()
        for o in outputs["main"]
        for t in o
    }
    assert set(exported["connections"]) <= names and linked <= names
    assert names - linked - set(exported["connections"]) == {"Note · LLM Gateway overview"}


def test_groq_call_retries_only_network_failures_and_never_throws_on_status() -> None:
    http = node(HTTP_NODE)
    parameters = http["parameters"]
    assert GROQ_URL in parameters["url"]
    assert http["credentials"]["httpHeaderAuth"]["name"] == "groq-api"
    assert parameters["options"]["timeout"] == 30000
    assert parameters["options"]["response"]["response"]["neverError"] is True
    assert parameters["options"]["response"]["response"]["fullResponse"] is True
    assert (http["retryOnFail"], http["maxTries"]) == (True, 3)
    assert http["onError"] == "continueRegularOutput"


def test_ledger_insert_has_no_retry_and_the_budget_read_fails_closed() -> None:
    log = node(LOG_NODE)
    assert "INSERT INTO llm_calls" in log["parameters"]["query"]
    assert "retryOnFail" not in log
    assert log["onError"] == "continueRegularOutput"
    budget = node(BUDGET_NODE)
    assert budget["parameters"]["query"].lstrip().startswith("SELECT")
    assert budget["onError"] == "continueRegularOutput"


def test_wait_reads_the_decided_delay_in_seconds() -> None:
    parameters = node(WAIT_NODE)["parameters"]
    assert parameters == {"amount": "={{ $json.wait_seconds }}", "unit": "seconds"}


def test_code_and_sql_carry_no_comment_lines() -> None:
    for path in (GATEWAY, WORKFLOW_A, WORKFLOW_B):
        for n in workflow(path)["nodes"]:
            source = n["parameters"].get("jsCode") or n["parameters"].get("query") or ""
            assert not COMMENT_LINE.search(source), n["name"]


@pytest.mark.parametrize("path", sorted(CALLERS))
def test_callers_run_the_gateway_once_per_item_and_wait_for_it(path: Path) -> None:
    caller = node(CALLERS[path], path)
    parameters = caller["parameters"]
    assert caller["type"] == "n8n-nodes-base.executeWorkflow"
    assert parameters["workflowId"]["value"] == GATEWAY_ID
    assert parameters["mode"] == "each"
    assert parameters["options"]["waitForSubWorkflow"] is True
    assert caller["onError"] == "continueRegularOutput"
    mapping = parameters["workflowInputs"]
    assert {c["id"]: c["type"] for c in mapping["schema"]} == INPUTS
    required = set(INPUTS) - {"batch_id", "run_id"}
    assert required <= set(mapping["value"]) <= set(INPUTS)


def test_b_passes_its_run_and_batch_to_the_ledger() -> None:
    values = node(CALLERS[WORKFLOW_B], WORKFLOW_B)["parameters"]["workflowInputs"]["value"]
    assert values["batch_id"] == "={{ $json.batch_id }}"
    assert values["run_id"] == "={{ Number($json.run_id) }}"


def test_only_the_gateway_talks_to_groq_or_writes_the_llm_ledger() -> None:
    for path in sorted(WORKFLOWS_DIR.glob("*.json")):
        for n in workflow(path)["nodes"]:
            text = json.dumps(n["parameters"], ensure_ascii=False)
            uses_groq = GROQ_URL in text or "groq-api" in json.dumps(n.get("credentials", {}))
            writes_ledger = "INSERT INTO llm_calls" in text
            if path != GATEWAY:
                assert not uses_groq and not writes_ledger, (path.name, n["name"])
    assert node(HTTP_NODE)["credentials"]["httpHeaderAuth"]["name"] == "groq-api"


def test_a_routes_the_gateway_answer_by_outcome() -> None:
    a = workflow(WORKFLOW_A)
    route = "Route · Gateway outcome"
    outputs = [[t["node"] for t in o] for o in a["connections"][route]["main"]]
    assert a["connections"][CALLERS[WORKFLOW_A]]["main"] == [
        [{"node": route, "type": "main", "index": 0}]
    ]
    assert outputs == [
        ["Coerce · Validate product"],
        ["Mark · Groq rate limited"],
        ["Mark · Groq call failed"],
    ]
    rules = node(route, WORKFLOW_A)["parameters"]["rules"]["values"]
    assert rules[0]["conditions"]["conditions"][0]["leftValue"] == "={{ $json.ok === true }}"
    assert rules[1]["conditions"]["conditions"][0]["rightValue"] == "rate_limited"
    names = {n["name"] for n in a["nodes"]}
    referenced = {
        ref
        for n in a["nodes"]
        for ref in NODE_REFERENCE.findall(json.dumps(n["parameters"], ensure_ascii=False))
    }
    assert "Prompt · Build LLM request" in referenced and referenced <= names
