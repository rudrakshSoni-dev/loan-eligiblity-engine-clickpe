"""Static checks on the exported Workflow C: every node reference and connection resolves.

n8n accepts a workflow whose expression names a node that no longer exists and fails only when that
expression runs, which for the failure branches may be never in a normal run.
"""

import json
import re
from typing import Any

from tests.workflow_c_helpers import (
    ANYTHING_NODE,
    CLAIM_NODE,
    DRY_RUN_NODE,
    FAIL_NODE,
    FINISH_NODE,
    GUARD_NODE,
    LOOP_NODE,
    MARK_NODE,
    PACE_NODE,
    RELEASE_NODE,
    SES_NODE,
    SPLIT_NODE,
    WORKFLOW_C,
    WORKFLOW_C_ID,
)

NODE_REFERENCE = re.compile(r"\$\('([^']+)'\)")
COMMENT_LINE = re.compile(r"^\s*(//|/\*|--)", re.MULTILINE)
TRIGGER_NODE = "Trigger · Matches ready (called by B)"
SENDING_TYPES = {
    "n8n-nodes-base.awsSes",
    "n8n-nodes-base.emailSend",
    "n8n-nodes-base.httpRequest",
}
TWO_WAY_TYPES = {"n8n-nodes-base.if", "n8n-nodes-base.splitInBatches"}
MAX_IN_PROCESS_WAIT_SECONDS = 60


def workflow() -> dict[str, Any]:
    exported: dict[str, Any] = json.loads(WORKFLOW_C.read_text(encoding="utf-8"))[0]
    return exported


def targets(node: str, output: int = 0) -> list[str]:
    return [t["node"] for t in workflow()["connections"][node]["main"][output]]


def node(name: str) -> dict[str, Any]:
    found: dict[str, Any] = next(n for n in workflow()["nodes"] if n["name"] == name)
    return found


def reachable_from_trigger(without: str) -> set[str]:
    connections = workflow()["connections"]
    seen = {TRIGGER_NODE}
    frontier = [TRIGGER_NODE]
    while frontier:
        current = frontier.pop()
        for output in connections.get(current, {"main": []})["main"]:
            for target in output:
                name = target["node"]
                if name != without and name not in seen:
                    seen.add(name)
                    frontier.append(name)
    return seen


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
    unreachable = names - linked - {TRIGGER_NODE}
    assert unreachable == {"Note · Workflow C overview"}


def test_main_path_runs_config_then_claim_then_compose_then_guard() -> None:
    assert targets(TRIGGER_NODE) == ["Check · Read batch_id"]
    assert targets("Check · Read batch_id") == ["Config · Load settings"]
    assert targets("Config · Load settings") == ["Config · Validate settings"]
    assert targets("Config · Validate settings") == ["Claim · matched to notifying"]
    assert targets("Claim · matched to notifying") == ["Check · Batch was claimed"]
    assert targets("Check · Batch was claimed", 0) == ["Compose · Select recipients"]
    assert targets("Check · Batch was claimed", 1) == ["Stop · Nothing to do (batch not matched)"]
    assert targets("Compose · Select recipients") == ["Compose · Build emails"]
    assert targets("Compose · Build emails") == [GUARD_NODE]
    assert targets(GUARD_NODE) == [DRY_RUN_NODE]


def test_after_the_guard_a_dry_run_releases_and_a_live_run_loops_send_mark_pace() -> None:
    assert targets(DRY_RUN_NODE, 0) == [RELEASE_NODE]
    assert targets(DRY_RUN_NODE, 1) == [ANYTHING_NODE]
    assert targets(ANYTHING_NODE, 0) == [SPLIT_NODE]
    assert targets(ANYTHING_NODE, 1) == [FINISH_NODE]
    assert targets(SPLIT_NODE) == [LOOP_NODE]
    assert targets(LOOP_NODE, 0) == [FINISH_NODE]
    assert targets(LOOP_NODE, 1) == [SES_NODE]
    assert targets(SES_NODE) == [MARK_NODE]
    assert targets(MARK_NODE) == [PACE_NODE]
    assert targets(PACE_NODE) == [LOOP_NODE]
    assert targets(FINISH_NODE) == []
    assert targets(RELEASE_NODE) == []


def test_without_the_guard_nothing_after_it_can_be_reached() -> None:
    after_guard = {
        DRY_RUN_NODE,
        ANYTHING_NODE,
        RELEASE_NODE,
        SPLIT_NODE,
        LOOP_NODE,
        SES_NODE,
        MARK_NODE,
        PACE_NODE,
        FINISH_NODE,
    }
    assert after_guard <= reachable_from_trigger(without="")
    assert not after_guard & reachable_from_trigger(without=GUARD_NODE)


def test_the_dry_run_switch_sends_only_when_dry_run_is_exactly_false() -> None:
    condition = node(DRY_RUN_NODE)["parameters"]["conditions"]
    assert condition["options"]["typeValidation"] == "strict"
    assert condition["conditions"] == [
        {
            "id": condition["conditions"][0]["id"],
            "leftValue": "={{ $json.dry_run }}",
            "rightValue": "",
            "operator": {"type": "boolean", "operation": "true", "singleValue": True},
        }
    ]


def test_only_a_run_with_emails_enters_the_loop() -> None:
    condition = node(ANYTHING_NODE)["parameters"]["conditions"]["conditions"][0]
    assert condition["leftValue"] == "={{ $json.emails.length }}"
    assert condition["operator"] == {"type": "number", "operation": "gt"}
    assert condition["rightValue"] == 0


def test_every_error_after_the_claim_marks_the_batch_failed_and_aborts_the_run() -> None:
    after_claim = (
        "Compose · Select recipients",
        "Compose · Build emails",
        GUARD_NODE,
        RELEASE_NODE,
        SPLIT_NODE,
        SES_NODE,
        MARK_NODE,
        FINISH_NODE,
    )
    for name in after_claim:
        assert targets(name, 1) == [FAIL_NODE], name
    assert targets(FAIL_NODE) == ["Abort · Stop and error"]
    assert targets("Claim · matched to notifying", 1) == ["Abort · Claim failed"]
    aborts = [n for n in workflow()["nodes"] if n["name"].startswith("Abort")]
    assert {n["type"] for n in aborts} == {"n8n-nodes-base.stopAndError"}


def test_error_outputs_are_enabled_exactly_where_they_are_wired() -> None:
    by_name = {n["name"]: n for n in workflow()["nodes"]}
    connections = workflow()["connections"]
    for name, outputs in connections.items():
        has_error_branch = len(outputs["main"]) > 1 and outputs["main"][1] != []
        two_way = by_name[name]["type"] in TWO_WAY_TYPES
        if has_error_branch and not two_way:
            assert by_name[name]["onError"] == "continueErrorOutput", name


def test_reads_ses_and_the_idempotent_mark_retry_and_state_changes_do_not() -> None:
    by_name = {n["name"]: n for n in workflow()["nodes"]}
    for name in ("Config · Load settings", "Compose · Select recipients", SES_NODE, MARK_NODE):
        assert by_name[name]["retryOnFail"] is True, name
        assert by_name[name]["maxTries"] == 3, name
        assert by_name[name]["waitBetweenTries"] <= MAX_IN_PROCESS_WAIT_SECONDS * 1000, name
    for name in (CLAIM_NODE, RELEASE_NODE, FAIL_NODE, FINISH_NODE):
        assert "retryOnFail" not in by_name[name], name


def test_every_database_node_uses_the_named_credential() -> None:
    for item in workflow()["nodes"]:
        if item["type"] == "n8n-nodes-base.postgres":
            assert item["credentials"]["postgres"]["name"] == "rds-postgres", item["name"]


def test_ses_is_the_only_sender_and_uses_the_role_credential_with_one_recipient() -> None:
    senders = [n for n in workflow()["nodes"] if n["type"] in SENDING_TYPES]
    assert [n["name"] for n in senders] == [SES_NODE]
    ses = senders[0]
    assert ses["type"] == "n8n-nodes-base.awsSes"
    assert ses["credentials"] == {
        "awsAssumeRole": {
            "id": ses["credentials"]["awsAssumeRole"]["id"],
            "name": "aws-ses-assume-role",
        }
    }
    assert ses["parameters"] == {
        "authentication": "assumeRole",
        "resource": "email",
        "operation": "send",
        "isBodyHtml": True,
        "subject": "={{ $json.subject }}",
        "body": "={{ $json.html }}",
        "fromEmail": "={{ $('Config · Validate settings').first().json.from_address }}",
        "toAddresses": ["={{ $json.to }}"],
        "additionalFields": {},
    }


def test_mark_reads_the_email_paired_with_this_send_not_the_first_one() -> None:
    replacement = node(MARK_NODE)["parameters"]["options"]["queryReplacement"]
    paired = f"$('{SPLIT_NODE}').item.json"
    assert replacement.count(paired) == 3
    assert ".first()" not in replacement
    assert "SendEmailResponse?.SendEmailResult?.MessageId" in replacement


def test_the_loop_sends_one_email_at_a_time_within_the_sandbox_rate() -> None:
    assert node(LOOP_NODE)["parameters"]["batchSize"] == 1
    pace = node(PACE_NODE)
    assert pace["type"] == "n8n-nodes-base.wait"
    assert pace["parameters"]["unit"] == "seconds"
    assert 1 <= pace["parameters"]["amount"] <= MAX_IN_PROCESS_WAIT_SECONDS


def test_finish_runs_once_and_reads_the_claim() -> None:
    finish = node(FINISH_NODE)
    assert finish["executeOnce"] is True
    replacement = finish["parameters"]["options"]["queryReplacement"]
    assert f"$('{CLAIM_NODE}').first().json.claimed_at" in replacement


def test_trigger_accepts_the_item_workflow_b_passes() -> None:
    trigger = workflow()["nodes"][1]
    assert trigger["type"] == "n8n-nodes-base.executeWorkflowTrigger"
    assert trigger["parameters"] == {"inputSource": "passthrough"}


def test_code_and_sql_carry_no_comment_lines() -> None:
    for item in workflow()["nodes"]:
        source = item["parameters"].get("jsCode") or item["parameters"].get("query") or ""
        assert not COMMENT_LINE.search(source), item["name"]


def test_sql_is_parameterised_and_never_interpolates_item_data() -> None:
    for item in workflow()["nodes"]:
        query = item["parameters"].get("query")
        if query is not None:
            assert "{{" not in query, item["name"]
