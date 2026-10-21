"""Static checks on the exported Workflow C: every node reference and connection resolves.

n8n accepts a workflow whose expression names a node that no longer exists and fails only when that
expression runs, which for the failure branches may be never in a normal run.
"""

import json
import re
from typing import Any

from tests.workflow_c_helpers import WORKFLOW_C, WORKFLOW_C_ID

NODE_REFERENCE = re.compile(r"\$\('([^']+)'\)")
COMMENT_LINE = re.compile(r"^\s*(//|/\*|--)", re.MULTILINE)
FAIL_NODE = "Fail · Mark batch failed (Notify)"
SENDING_TYPES = {
    "n8n-nodes-base.awsSes",
    "n8n-nodes-base.emailSend",
    "n8n-nodes-base.httpRequest",
}


def workflow() -> dict[str, Any]:
    exported: dict[str, Any] = json.loads(WORKFLOW_C.read_text(encoding="utf-8"))[0]
    return exported


def targets(node: str, output: int = 0) -> list[str]:
    return [t["node"] for t in workflow()["connections"][node]["main"][output]]


def test_identity_and_hygiene() -> None:
    exported = workflow()
    nodes = exported["nodes"]
    assert exported["id"] == WORKFLOW_C_ID
    assert exported["active"] is False
    assert exported["pinData"] == {}
    assert len({n["name"] for n in nodes}) == len(nodes)
    assert len({n["id"] for n in nodes}) == len(nodes)
    assert all("·" in n["name"] for n in nodes)


def test_every_expression_reference_names_an_existing_node() -> None:
    nodes = workflow()["nodes"]
    names = {n["name"] for n in nodes}
    sources = [json.dumps(n["parameters"], ensure_ascii=False) for n in nodes]
    referenced = {ref for source in sources for ref in NODE_REFERENCE.findall(source)}
    assert {"Check · Read batch_id", "Config · Validate settings"} <= referenced
    assert referenced <= names


def test_every_connection_joins_existing_nodes() -> None:
    exported = workflow()
    names = {n["name"] for n in exported["nodes"]}
    linked = {
        t["node"]
        for outputs in exported["connections"].values()
        for output in outputs["main"]
        for t in output
    }
    assert set(exported["connections"]) <= names
    assert linked <= names
    unreachable = names - linked - {"Trigger · Matches ready (called by B)"}
    assert unreachable == {"Note · Workflow C overview"}


def test_main_path_runs_config_then_claim_then_compose_then_guard_then_release() -> None:
    assert targets("Trigger · Matches ready (called by B)") == ["Check · Read batch_id"]
    assert targets("Check · Read batch_id") == ["Config · Load settings"]
    assert targets("Config · Load settings") == ["Config · Validate settings"]
    assert targets("Config · Validate settings") == ["Claim · matched to notifying"]
    assert targets("Claim · matched to notifying") == ["Check · Batch was claimed"]
    assert targets("Check · Batch was claimed", 0) == ["Compose · Select recipients"]
    assert targets("Check · Batch was claimed", 1) == ["Stop · Nothing to do (batch not matched)"]
    assert targets("Compose · Select recipients") == ["Compose · Build emails"]
    assert targets("Compose · Build emails") == ["Guard · Recipients are test inboxes"]
    assert targets("Guard · Recipients are test inboxes") == ["Release · notifying back to matched"]


def test_the_guard_sits_between_composing_and_everything_that_follows() -> None:
    connections = workflow()["connections"]
    into_release = [
        name
        for name, outputs in connections.items()
        if any(t["node"] == "Release · notifying back to matched" for t in outputs["main"][0])
    ]
    assert into_release == ["Guard · Recipients are test inboxes"]


def test_every_error_after_the_claim_marks_the_batch_failed_and_aborts_the_run() -> None:
    for node in ("Compose · Select recipients", "Compose · Build emails"):
        assert targets(node, 1) == [FAIL_NODE]
    assert targets("Guard · Recipients are test inboxes", 1) == [FAIL_NODE]
    assert targets("Release · notifying back to matched", 1) == [FAIL_NODE]
    assert targets(FAIL_NODE) == ["Abort · Stop and error"]
    assert targets("Claim · matched to notifying", 1) == ["Abort · Claim failed"]
    aborts = [n for n in workflow()["nodes"] if n["name"].startswith("Abort")]
    assert {n["type"] for n in aborts} == {"n8n-nodes-base.stopAndError"}


def test_error_outputs_are_enabled_exactly_where_they_are_wired() -> None:
    by_name = {n["name"]: n for n in workflow()["nodes"]}
    connections = workflow()["connections"]
    for name, outputs in connections.items():
        has_error_branch = len(outputs["main"]) > 1 and outputs["main"][1] != []
        is_if = by_name[name]["type"] == "n8n-nodes-base.if"
        if has_error_branch and not is_if:
            assert by_name[name]["onError"] == "continueErrorOutput", name


def test_reads_retry_and_writes_do_not() -> None:
    by_name = {n["name"]: n for n in workflow()["nodes"]}
    for name in ("Config · Load settings", "Compose · Select recipients"):
        assert by_name[name]["retryOnFail"] is True
        assert by_name[name]["maxTries"] == 3
    for name in ("Claim · matched to notifying", "Release · notifying back to matched", FAIL_NODE):
        assert "retryOnFail" not in by_name[name], name


def test_every_database_node_uses_the_named_credential_and_nothing_sends_mail() -> None:
    nodes = workflow()["nodes"]
    for node in nodes:
        if node["type"] == "n8n-nodes-base.postgres":
            assert node["credentials"]["postgres"]["name"] == "rds-postgres", node["name"]
    assert not SENDING_TYPES & {n["type"] for n in nodes}


def test_trigger_accepts_the_item_workflow_b_passes() -> None:
    trigger = workflow()["nodes"][1]
    assert trigger["type"] == "n8n-nodes-base.executeWorkflowTrigger"
    assert trigger["parameters"] == {"inputSource": "passthrough"}


def test_code_and_sql_carry_no_comment_lines() -> None:
    for node in workflow()["nodes"]:
        source = node["parameters"].get("jsCode") or node["parameters"].get("query") or ""
        assert not COMMENT_LINE.search(source), node["name"]


def test_sql_is_parameterised_and_never_interpolates_item_data() -> None:
    for node in workflow()["nodes"]:
        query = node["parameters"].get("query")
        if query is not None:
            assert "{{" not in query, node["name"]
