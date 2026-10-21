"""The LLM Gateway's node names, file path and a driver that runs its Code nodes as n8n chains them.

`run_gateway` feeds one request through `Prepare`, then repeats `Attempt` -> fake Groq reply ->
`Read` -> `Restore` while `Read` asks for a retry, and ends with `Return`, exactly as the workflow's
loop through `Wait · Rate-limit backoff` does. Every request body sent and every `llm_calls` row
the `Log` node would write is kept, so tests can check the whole conversation with Groq.
"""

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.workflow_b_helpers import run_code_node, workflow_node

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / "n8n" / "workflows"
GATEWAY = WORKFLOWS_DIR / "workflow-g-llm-gateway.json"
GATEWAY_ID = "wfllmgateway01"

TRIGGER_NODE = "Trigger · Called by A or B"
BUDGET_NODE = "Budget · Usage last 24 h"
PREPARE_NODE = "Prepare · Check request + budget"
CHECK_NODE = "Check · Request accepted"
ATTEMPT_NODE = "Attempt · Build Groq body"
HTTP_NODE = "LLM · Groq chat completion"
READ_NODE = "Read · Classify reply"
LOG_NODE = "Log · llm_calls"
RESTORE_NODE = "Restore · Reply state"
ROUTE_NODE = "Route · Retry or return"
WAIT_NODE = "Wait · Rate-limit backoff"
RETURN_NODE = "Return · Gateway result"

PRIMARY = "openai/gpt-oss-120b"
FALLBACK = "openai/gpt-oss-20b"
LOG_PARAMS = {f"${i}": f":p{i}" for i in range(1, 9)}
MAX_LOOPS = 20

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "eligible": {"type": "boolean"},
        "score": {"type": ["integer", "null"]},
        "groups": {
            "type": ["array", "null"],
            "items": {"type": "string", "enum": ["Salaried", "Business"]},
        },
    },
    "required": ["eligible", "score", "groups"],
    "additionalProperties": False,
}

Reply = dict[str, Any]


def gateway_request(**changes: Any) -> dict[str, Any]:
    request: dict[str, Any] = {
        "purpose": "gateway_check",
        "model": PRIMARY,
        "system": "Answer with JSON.",
        "user": "Is a score of 700 enough?",
        "schema_name": "check_answer",
        "json_schema": ANSWER_SCHEMA,
        "max_tokens": 200,
        "batch_id": None,
        "run_id": None,
    }
    return {**request, **changes}


def js_constant(node: str, name: str) -> int:
    code = workflow_node(node, GATEWAY)["parameters"]["jsCode"]
    found = re.search(rf"const {name} = (\d+);", code)
    assert found is not None, name
    return int(found.group(1))


def ok_reply(
    answer: Any = None,
    tokens: tuple[int, int] = (150, 40),
    model: str = PRIMARY,
    finish_reason: str = "stop",
) -> Reply:
    content = json.dumps(
        {"eligible": True, "score": 700, "groups": ["Salaried"]} if answer is None else answer
    )
    return {
        "statusCode": 200,
        "headers": {},
        "body": {
            "model": model,
            "choices": [{"finish_reason": finish_reason, "message": {"content": content}}],
            "usage": {
                "prompt_tokens": tokens[0],
                "completion_tokens": tokens[1],
                "total_time": 0.25,
            },
        },
    }


def status_reply(status: int, retry_after: str | None = None, message: str = "limit") -> Reply:
    headers = {} if retry_after is None else {"retry-after": retry_after}
    return {"statusCode": status, "headers": headers, "body": {"error": {"message": message}}}


@dataclass
class GatewayRun:
    result: dict[str, Any]
    sent: list[dict[str, Any]] = field(default_factory=list)
    logged: list[dict[str, Any]] = field(default_factory=list)
    waits: list[int] = field(default_factory=list)


def only_json(output: Any) -> dict[str, Any]:
    if isinstance(output, list):
        assert len(output) == 1
        output = output[0]
    item: dict[str, Any] = output["json"]
    return item


def prepare(
    request: dict[str, Any] | list[dict[str, Any]], ledger: dict[str, Any]
) -> dict[str, Any]:
    """Run `Prepare` with `ledger` as the output of the budget query (`{"usage": {...}}`)."""
    requests = request if isinstance(request, list) else [request]
    return only_json(run_code_node(PREPARE_NODE, ledger, {TRIGGER_NODE: requests}, GATEWAY))


def reply_source(
    replies: list[Reply] | Callable[[dict[str, Any]], Reply],
) -> Callable[[dict[str, Any]], Reply]:
    if callable(replies):
        return replies
    queue: Iterator[Reply] = iter(replies)
    return lambda _: next(queue)


def run_gateway(
    request: dict[str, Any],
    replies: list[Reply] | Callable[[dict[str, Any]], Reply],
    usage: dict[str, Any] | None = None,
) -> GatewayRun:
    """Drive the gateway for one request with the given Groq replies and 24 h usage per model."""
    return finish_run(prepare(request, {"usage": usage or {}}), replies)


def finish_run(
    state: dict[str, Any], replies: list[Reply] | Callable[[dict[str, Any]], Reply]
) -> GatewayRun:
    groq = reply_source(replies)
    run = GatewayRun(result={})
    loops = 0
    while state["next"] in ("call", "retry"):
        loops += 1
        assert loops <= MAX_LOOPS, "gateway did not stop retrying"
        if state["next"] == "retry":
            run.waits.append(state["wait_seconds"])
        attempt = only_json(run_code_node(ATTEMPT_NODE, state, workflow_file=GATEWAY))
        run.sent.append(attempt["groq_request"])
        read = only_json(
            run_code_node(
                READ_NODE, groq(attempt["groq_request"]), {ATTEMPT_NODE: [attempt]}, GATEWAY
            )
        )
        run.logged.append(read["log"])
        state = only_json(run_code_node(RESTORE_NODE, {"id": "1"}, {READ_NODE: [read]}, GATEWAY))
    run.result = only_json(run_code_node(RETURN_NODE, state, workflow_file=GATEWAY))
    return run
