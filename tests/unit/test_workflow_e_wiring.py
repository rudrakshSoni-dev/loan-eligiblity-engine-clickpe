"""Static and Code-node checks on the exported Workflow E (global error handler)."""

import json
import re
from typing import Any

import pytest

from tests.workflow_b_helpers import NODE_BINARY, run_code_node
from tests.workflow_e_helpers import (
    CHECK_NODE,
    FAILED_NODE,
    FORMAT_NODE,
    INSERT_NODE,
    LOAD_NODE,
    SENT_NODE,
    SES_NODE,
    TRIGGER_NODE,
    WORKFLOW_E,
    WORKFLOW_E_ID,
    WORKFLOWS_DIR,
)

NODE_REFERENCE = re.compile(r"\$\('([^']+)'\)")
COMMENT_LINE = re.compile(r"^\s*(//|/\*)", re.MULTILINE)
needs_node = pytest.mark.skipif(NODE_BINARY is None, reason="node not installed")


def workflow() -> dict[str, Any]:
    exported: dict[str, Any] = json.loads(WORKFLOW_E.read_text(encoding="utf-8"))[0]
    return exported


def targets(node: str, output: int = 0) -> list[str]:
    return [t["node"] for t in workflow()["connections"][node]["main"][output]]


def node(name: str) -> dict[str, Any]:
    found: dict[str, Any] = next(n for n in workflow()["nodes"] if n["name"] == name)
    return found


def test_identity_and_hygiene() -> None:
    exported = workflow()
    nodes = exported["nodes"]
    assert exported["id"] == WORKFLOW_E_ID
    assert exported["active"] is False
    assert exported["pinData"] == {}
    assert "errorWorkflow" not in exported["settings"]
    assert len({n["name"] for n in nodes}) == len(nodes)
    assert len({n["id"] for n in nodes}) == len(nodes)
    assert all("·" in n["name"] for n in nodes)
    assert not any(COMMENT_LINE.search(n["parameters"].get("jsCode", "")) for n in nodes)


def test_every_expression_reference_and_connection_names_an_existing_node() -> None:
    exported = workflow()
    names = {n["name"] for n in exported["nodes"]}
    sources = [json.dumps(n["parameters"], ensure_ascii=False) for n in exported["nodes"]]
    referenced = {ref for source in sources for ref in NODE_REFERENCE.findall(source)}
    linked = {
        t["node"]
        for outputs in exported["connections"].values()
        for output in outputs["main"]
        for t in output
    }
    assert referenced <= names
    assert set(exported["connections"]) <= names
    assert linked <= names
    assert names - linked - {TRIGGER_NODE} == {"Note · Workflow E overview"}


def test_main_path_records_before_it_alerts_and_alerts_only_after_the_recipient_check() -> None:
    assert targets(TRIGGER_NODE) == [FORMAT_NODE]
    assert targets(FORMAT_NODE) == [INSERT_NODE]
    assert targets(INSERT_NODE) == [LOAD_NODE]
    assert targets(LOAD_NODE) == [CHECK_NODE]
    assert targets(CHECK_NODE) == [SES_NODE]
    assert targets(SES_NODE, 0) == [SENT_NODE]
    assert targets(SES_NODE, 1) == [FAILED_NODE]


def test_a_failed_insert_does_not_stop_the_alert_and_ses_failure_is_recorded() -> None:
    assert node(INSERT_NODE)["onError"] == "continueRegularOutput"
    assert node(INSERT_NODE)["maxTries"] == 3
    assert node(SES_NODE)["onError"] == "continueErrorOutput"
    assert node(SES_NODE)["maxTries"] == 3
    assert node(SES_NODE)["credentials"]["awsAssumeRole"]["name"] == "aws-ses-assume-role"


@pytest.mark.parametrize(
    "file_name",
    [
        "workflow-a-product-discovery.json",
        "workflow-b-matching.json",
        "workflow-c-notification.json",
    ],
)
def test_every_other_workflow_names_e_as_its_error_workflow(file_name: str) -> None:
    other = json.loads((WORKFLOWS_DIR / file_name).read_text(encoding="utf-8"))[0]
    assert other["settings"]["errorWorkflow"] == WORKFLOW_E_ID


@needs_node
def test_format_flattens_an_execution_error() -> None:
    payload = {
        "workflow": {"id": "w1", "name": "B · Matching"},
        "execution": {
            "id": "77",
            "url": "http://localhost:5678/workflow/w1/executions/77",
            "mode": "webhook",
            "lastNodeExecuted": "Stage 1 · SQL pre-filter",
            "error": {"message": "boom", "stack": "Error: boom\n at x"},
        },
    }
    out = run_code_node(FORMAT_NODE, {**payload}, workflow_file=WORKFLOW_E)[0]["json"]
    assert out["workflow_name"] == "B · Matching"
    assert out["node_name"] == "Stage 1 · SQL pre-filter"
    assert out["execution_id"] == "77"
    assert out["mode"] == "webhook"
    assert out["subject"] == "[TEST] n8n error · B · Matching · Stage 1 · SQL pre-filter"
    assert "Error: boom" in out["text"]


@needs_node
def test_format_handles_a_failed_trigger_payload() -> None:
    payload = {
        "workflow": {"id": "w2", "name": "A · Discovery"},
        "trigger": {"error": {"message": "cron failed"}, "mode": "trigger"},
    }
    out = run_code_node(FORMAT_NODE, payload, workflow_file=WORKFLOW_E)[0]["json"]
    assert out["error_message"] == "cron failed"
    assert out["mode"] == "trigger"
    assert out["execution_id"] == ""


@needs_node
def test_format_truncates_and_strips_control_characters_from_the_subject() -> None:
    payload = {
        "workflow": {"id": "w3", "name": "Bad\r\nBcc: x@y.z"},
        "execution": {"error": {"message": "m" * 5000, "stack": "s" * 9000}},
    }
    out = run_code_node(FORMAT_NODE, payload, workflow_file=WORKFLOW_E)[0]["json"]
    assert "\n" not in out["subject"]
    assert "\r" not in out["subject"]
    assert len(out["error_message"]) == 2000
    assert len(out["error_stack"]) == 4000


@needs_node
def test_format_survives_an_empty_payload() -> None:
    out = run_code_node(FORMAT_NODE, {}, workflow_file=WORKFLOW_E)[0]["json"]
    assert out["workflow_name"] == "unknown workflow"
    assert out["error_message"] == "no error message in the payload"


def check(to: str | None, allowed: Any, sender: str | None = "me@example.invalid") -> Any:
    return run_code_node(
        CHECK_NODE,
        {"to_address": to, "from_address": sender},
        nodes={
            LOAD_NODE: [{"test_inbox_aliases": allowed}],
            FORMAT_NODE: [{"subject": "s", "text": "t"}],
            INSERT_NODE: [{"id": "5"}],
        },
        workflow_file=WORKFLOW_E,
    )


@needs_node
def test_check_passes_an_allowed_recipient_with_the_record_id() -> None:
    out = check("a@example.invalid", ["a@example.invalid", "b@example.invalid"])[0]["json"]
    assert out == {
        "to": "a@example.invalid",
        "from": "me@example.invalid",
        "subject": "s",
        "text": "t",
        "record_id": "5",
    }


@needs_node
@pytest.mark.parametrize(
    ("to", "allowed", "sender"),
    [
        ("c@example.invalid", ["a@example.invalid"], "me@example.invalid"),
        (None, ["a@example.invalid"], "me@example.invalid"),
        ("a@example.invalid", None, "me@example.invalid"),
        ("a@example.invalid", ["a@example.invalid"], None),
    ],
)
def test_check_refuses_anything_but_an_allowed_recipient_and_a_sender(
    to: str | None, allowed: Any, sender: str | None
) -> None:
    with pytest.raises(Exception, match="no alert sent"):
        check(to, allowed, sender)
