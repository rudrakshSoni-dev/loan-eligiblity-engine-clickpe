"""Static checks on the exported Workflow B: every node reference resolves and nothing is left over.

n8n accepts a workflow whose expression names a node that no longer exists and fails only when that
expression runs, which for the failure branches may be never in a normal run.
"""

import json
import re
from typing import Any

import pytest

from tests.workflow_b_helpers import NODE_BINARY, WORKFLOW, run_code_node
from tests.workflow_c_helpers import WORKFLOW_C_ID

NODE_REFERENCE = re.compile(r"\$\('([^']+)'\)")
TRIGGER_NODE = "Trigger · Batch processed (match-batch)"
READ_BATCH_NODE = "Check · Read batch_id"
BATCH = "00000000-0000-4000-8000-0000000000aa"
OTHER_BATCH = "00000000-0000-4000-8000-0000000000bb"
needs_node = pytest.mark.skipif(NODE_BINARY is None, reason="node not installed")
COMMENT_LINE = re.compile(r"^\s*(//|/\*|--)", re.MULTILINE)


def workflow() -> dict[str, Any]:
    exported: dict[str, Any] = json.loads(WORKFLOW.read_text(encoding="utf-8"))[0]
    return exported


def test_node_names_and_ids_are_unique_and_no_data_is_pinned() -> None:
    nodes = workflow()["nodes"]
    assert len({n["name"] for n in nodes}) == len(nodes)
    assert len({n["id"] for n in nodes}) == len(nodes)
    assert workflow()["pinData"] == {}


def test_every_expression_reference_names_an_existing_node() -> None:
    nodes = workflow()["nodes"]
    names = {n["name"] for n in nodes}
    referenced = {
        ref
        for n in nodes
        for ref in NODE_REFERENCE.findall(json.dumps(n["parameters"], ensure_ascii=False))
    }
    assert "Stage 3 · Build LLM requests" in referenced
    assert referenced <= names


def test_every_connection_joins_existing_nodes() -> None:
    exported = workflow()
    names = {n["name"] for n in exported["nodes"]}
    targets = {
        t["node"]
        for outputs in exported["connections"].values()
        for output in outputs["main"]
        for t in output
    }
    assert set(exported["connections"]) <= names
    assert targets <= names
    assert names - targets - set(exported["connections"]) == {"Note · Workflow B overview"}


def test_statistics_refresh_and_stage_3_branches_are_wired() -> None:
    connections = workflow()["connections"]

    def targets(node: str, output: int = 0) -> list[str]:
        return [t["node"] for t in connections[node]["main"][output]]

    assert targets("Record · Stage 1 funnel") == ["Stage 1 · Refresh planner statistics"]
    assert targets("Stage 1 · Refresh planner statistics") == ["Stage 2 · Load product rules"]
    assert targets("Record · Stage 2 funnel") == ["Stage 3 · Form cohorts"]
    assert targets("Check · Any cohort to ask Groq", 0) == ["Stage 3 · One item per request"]
    assert targets("Check · Any cohort to ask Groq", 1) == ["Stage 3 · Read verdicts"]
    assert targets("Stage 3 · One item per request") == ["LLM · Judge cohorts (LLM Gateway)"]
    assert targets("LLM · Judge cohorts (LLM Gateway)") == ["Stage 3 · Read verdicts"]


def test_code_and_sql_carry_no_comment_lines() -> None:
    for node in workflow()["nodes"]:
        source = node["parameters"].get("jsCode") or node["parameters"].get("query") or ""
        assert not COMMENT_LINE.search(source), node["name"]


def test_persist_follows_stage_3_and_every_persist_error_marks_the_batch_failed() -> None:
    connections = workflow()["connections"]

    def targets(node: str, output: int = 0) -> list[str]:
        return [t["node"] for t in connections[node]["main"][output]]

    assert targets("Record · Stage 3 funnel") == ["Persist · Insert matches"]
    assert targets("Persist · Insert matches") == ["Persist · Finalize run + mark matched"]
    assert targets("Persist · Finalize run + mark matched") == ["Notify · Run Workflow C"]
    assert "Notify · Run Workflow C" not in connections
    for node in ("Persist · Insert matches", "Persist · Finalize run + mark matched"):
        assert targets(node, 1) == ["Fail · Mark batch failed (Persist)"]
    assert "Fail · Mark batch failed (Persist)" not in connections


def test_workflow_c_hand_off_names_the_exported_workflow_and_does_not_wait() -> None:
    notify = next(n for n in workflow()["nodes"] if n["name"] == "Notify · Run Workflow C")
    assert notify["type"] == "n8n-nodes-base.executeWorkflow"
    assert notify["parameters"]["workflowId"]["value"] == WORKFLOW_C_ID
    assert notify["parameters"]["options"] == {"waitForSubWorkflow": False}


def test_the_trigger_takes_only_a_signed_token_from_inside_the_vpc() -> None:
    trigger = next(n for n in workflow()["nodes"] if n["name"] == TRIGGER_NODE)
    assert trigger["typeVersion"] >= 2
    assert trigger["parameters"]["authentication"] == "jwtAuth"
    assert trigger["parameters"]["options"]["ipWhitelist"] == "172.31.0.0/16"
    assert trigger["credentials"] == {"jwtAuth": {"id": "WebhookJwtHs256A", "name": "webhook-jwt"}}
    assert "httpHeaderAuth" not in json.dumps(workflow())


@needs_node
@pytest.mark.parametrize(
    ("jwt_payload", "body", "valid"),
    [
        ({"batch_id": BATCH}, {"batch_id": BATCH}, True),
        ({"batch_id": OTHER_BATCH}, {"batch_id": BATCH}, False),
        ({}, {"batch_id": BATCH}, False),
        (None, {"batch_id": BATCH}, False),
        ({"batch_id": BATCH.upper()}, {"batch_id": BATCH.upper()}, False),
        ({"batch_id": ""}, {}, False),
    ],
)
def test_the_body_batch_id_must_be_the_one_the_token_was_signed_for(
    jwt_payload: dict[str, str] | None, body: dict[str, str], valid: bool
) -> None:
    request: dict[str, Any] = {"headers": {}, "body": body}
    if jwt_payload is not None:
        request["jwtPayload"] = jwt_payload
    [output] = run_code_node(READ_BATCH_NODE, request)
    assert output["json"]["batch_id_valid"] is valid
    assert output["json"]["batch_id"] == body.get("batch_id", "")
