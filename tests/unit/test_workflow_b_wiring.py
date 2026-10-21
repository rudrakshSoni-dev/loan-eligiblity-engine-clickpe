"""Static checks on the exported Workflow B: every node reference resolves and nothing is left over.

n8n accepts a workflow whose expression names a node that no longer exists and fails only when that
expression runs, which for the failure branches may be never in a normal run.
"""

import json
import re
from typing import Any

from tests.workflow_b_helpers import WORKFLOW

NODE_REFERENCE = re.compile(r"\$\('([^']+)'\)")
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
    assert sorted(targets("LLM · Judge cohorts (Groq)")) == [
        "Log · llm_calls (Stage 3)",
        "Stage 3 · Read verdicts",
    ]


def test_code_and_sql_carry_no_comment_lines() -> None:
    for node in workflow()["nodes"]:
        source = node["parameters"].get("jsCode") or node["parameters"].get("query") or ""
        assert not COMMENT_LINE.search(source), node["name"]
