"""The LLM Gateway's exported Code nodes under Node.js, chained as n8n chains them.

Groq is replaced by replies shaped like the real ones recorded in T30 and T35 (200 with usage,
429 with `retry-after`, 5xx, 401, no response). Each test drives the full Prepare -> Attempt ->
Read -> Restore loop, so the retry, wait and fallback decisions are checked end to end.
"""

import subprocess
from typing import Any

import pytest

from tests.workflow_b_helpers import NODE_BINARY
from tests.workflow_gateway_helpers import (
    FALLBACK,
    PREPARE_NODE,
    PRIMARY,
    READ_NODE,
    gateway_request,
    js_constant,
    ok_reply,
    prepare,
    run_gateway,
    status_reply,
)

pytestmark = pytest.mark.skipif(NODE_BINARY is None, reason="node not installed")

BATCH = "0b0e8f3c-6d2a-4c1e-9f7a-1d2c3b4a5e6f"
PUBLIC_FIELDS = {
    "ok",
    "data",
    "error_kind",
    "error",
    "status",
    "finish_reason",
    "model",
    "requested_model",
    "fallback_used",
    "fallback_reason",
    "tokens",
    "prompt_tokens",
    "completion_tokens",
    "latency_ms",
    "attempts",
    "rate_limit_waits",
    "waited_seconds",
    "estimated_tokens",
}


def test_a_valid_answer_is_returned_parsed_with_its_cost_and_one_ledger_row() -> None:
    request = gateway_request(batch_id=BATCH, run_id=12)

    run = run_gateway(request, [ok_reply(tokens=(150, 40))])

    assert set(run.result) == PUBLIC_FIELDS
    assert run.result["ok"] is True
    assert run.result["data"] == {"eligible": True, "score": 700, "groups": ["Salaried"]}
    assert (run.result["model"], run.result["fallback_used"]) == (PRIMARY, False)
    assert (run.result["tokens"], run.result["attempts"], run.result["latency_ms"]) == (190, 1, 250)
    assert run.result["error_kind"] is None and run.waits == []
    assert run.logged == [
        {
            "purpose": "gateway_check",
            "model": PRIMARY,
            "prompt_tokens": 150,
            "completion_tokens": 40,
            "status": 200,
            "latency_ms": 250,
            "batch_id": BATCH,
            "run_id": 12,
        }
    ]


def test_groq_body_is_strict_schema_temperature_zero_low_reasoning() -> None:
    run = run_gateway(gateway_request(max_tokens=321), [ok_reply()])

    body = run.sent[0]
    assert body["model"] == PRIMARY
    assert (body["temperature"], body["reasoning_effort"], body["include_reasoning"]) == (
        0,
        "low",
        False,
    )
    assert body["max_completion_tokens"] == 321
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["messages"][1]["content"] == "Is a score of 700 enough?"
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "check_answer",
            "strict": True,
            "schema": gateway_request()["json_schema"],
        },
    }


def test_more_than_one_request_per_execution_is_an_error() -> None:
    with pytest.raises(subprocess.CalledProcessError) as raised:
        prepare([gateway_request(), gateway_request()], {"usage": {}})

    assert "exactly one request per execution, got 2" in raised.value.stderr


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"purpose": "Bad Purpose"}, "purpose must be"),
        ({"model": "llama-3"}, "model must be one of openai/gpt-oss-120b, openai/gpt-oss-20b"),
        ({"system": "  "}, "system must be a non-empty string"),
        ({"user": None}, "user must be a non-empty string"),
        ({"schema_name": "has space"}, "schema_name must be"),
        ({"json_schema": {"type": "array"}}, "root type is object"),
        ({"json_schema": "{}"}, "root type is object"),
        ({"max_tokens": 0}, "max_tokens must be a whole number from 1 to 4000"),
        ({"max_tokens": 4001}, "max_tokens must be"),
        ({"max_tokens": 1.5}, "max_tokens must be"),
        ({"batch_id": "not-a-uuid"}, "batch_id must be a UUID"),
        ({"run_id": 5}, "run_id needs a batch_id"),
        ({"batch_id": BATCH, "run_id": -1}, "run_id must be a positive whole number"),
    ],
)
def test_malformed_requests_are_refused_without_calling_groq(
    changes: dict[str, Any], expected: str
) -> None:
    run = run_gateway(gateway_request(**changes), [])

    assert run.result["ok"] is False
    assert run.result["error_kind"] == "bad_request"
    assert expected in run.result["error"]
    assert run.sent == [] and run.result["attempts"] == 0


def test_numeric_text_ids_from_callers_are_accepted() -> None:
    run = run_gateway(gateway_request(batch_id=BATCH, run_id="17", max_tokens="200"), [ok_reply()])

    assert run.result["ok"] is True
    assert run.logged[0]["run_id"] == 17


def test_a_request_larger_than_the_tokens_per_minute_limit_is_refused() -> None:
    limit = js_constant(PREPARE_NODE, "TOKENS_PER_MINUTE_LIMIT")

    run = run_gateway(gateway_request(user="x" * (3 * limit), max_tokens=10), [])

    assert run.result["error_kind"] == "bad_request"
    assert f"more than Groq's {limit} tokens per minute" in run.result["error"]
    assert run.result["estimated_tokens"] > limit and run.sent == []


def test_an_unreadable_ledger_refuses_instead_of_spending_blind() -> None:
    state = prepare(gateway_request(), {"error": "connection refused"})

    assert state["next"] == "return"
    assert state["outcome"]["error_kind"] == "budget"
    assert "ledger could not be read" in state["outcome"]["error"]


def test_budget_boundary_is_exact_and_an_exhausted_primary_uses_the_fallback() -> None:
    daily = js_constant(PREPARE_NODE, "DAILY_TOKEN_BUDGET")
    estimate = prepare(gateway_request(), {"usage": {}})["estimated_tokens"]

    exactly = run_gateway(gateway_request(), [ok_reply()], {PRIMARY: {"tokens": daily - estimate}})
    over = run_gateway(
        gateway_request(), [ok_reply(model=FALLBACK)], {PRIMARY: {"tokens": daily - estimate + 1}}
    )

    assert (exactly.result["model"], exactly.result["fallback_used"]) == (PRIMARY, False)
    assert over.sent[0]["model"] == FALLBACK
    assert (over.result["fallback_used"], over.result["fallback_reason"]) == (True, "budget")


def test_daily_call_cap_counts_too_and_both_models_spent_is_a_budget_refusal() -> None:
    calls = js_constant(PREPARE_NODE, "DAILY_REQUEST_BUDGET")
    daily = js_constant(PREPARE_NODE, "DAILY_TOKEN_BUDGET")
    usage = {PRIMARY: {"tokens": 0, "calls": calls}, FALLBACK: {"tokens": daily, "calls": 0}}

    run = run_gateway(gateway_request(), [], usage)

    assert run.result["error_kind"] == "budget"
    assert f"{daily} tokens, {calls} calls per model" in run.result["error"]
    assert run.sent == []


def test_a_fallback_only_request_never_switches_models() -> None:
    daily = js_constant(PREPARE_NODE, "DAILY_TOKEN_BUDGET")

    run = run_gateway(gateway_request(model=FALLBACK), [], {FALLBACK: {"tokens": daily}})

    assert run.result["error_kind"] == "budget" and run.sent == []


def test_429_waits_retry_after_plus_one_second_then_succeeds() -> None:
    run = run_gateway(gateway_request(), [status_reply(429, "21"), ok_reply()])

    assert run.waits == [22]
    assert run.result["ok"] is True
    assert (run.result["attempts"], run.result["rate_limit_waits"]) == (2, 1)
    assert run.result["waited_seconds"] == 22
    assert [r["status"] for r in run.logged] == [429, 200]
    assert run.logged[0]["prompt_tokens"] is None and run.result["tokens"] == 190


def test_429_without_retry_after_waits_the_default() -> None:
    run = run_gateway(gateway_request(), [status_reply(429), ok_reply()])

    assert run.waits == [js_constant(READ_NODE, "DEFAULT_WAIT_SECONDS")]


def test_three_waits_then_one_switch_to_the_20b_model() -> None:
    replies = [status_reply(429, "5")] * 4 + [ok_reply(model=FALLBACK)]

    run = run_gateway(gateway_request(), replies)

    assert run.waits == [6, 6, 6, js_constant(READ_NODE, "SWITCH_WAIT_SECONDS")]
    assert [body["model"] for body in run.sent] == [PRIMARY] * 4 + [FALLBACK]
    assert run.result["ok"] is True and run.result["model"] == FALLBACK
    assert (run.result["fallback_used"], run.result["fallback_reason"]) == (True, "rate_limited")
    assert (run.result["attempts"], run.result["rate_limit_waits"]) == (5, 3)
    assert [r["model"] for r in run.logged] == [PRIMARY] * 4 + [FALLBACK]


def test_a_retry_after_beyond_60_seconds_switches_without_waiting_it_out() -> None:
    assert js_constant(READ_NODE, "MAX_WAIT_SECONDS") <= 60

    run = run_gateway(gateway_request(), [status_reply(429, "60"), ok_reply(model=FALLBACK)])

    assert run.waits == [js_constant(READ_NODE, "SWITCH_WAIT_SECONDS")]
    assert run.result["fallback_reason"] == "rate_limited"


def test_rate_limit_on_both_models_ends_with_the_reason_and_never_loops_forever() -> None:
    run = run_gateway(gateway_request(), lambda _: status_reply(429, "2", "TPM limit 8000"))

    waits_per_model = js_constant(READ_NODE, "MAX_WAITS_PER_MODEL")
    assert run.result["ok"] is False and run.result["error_kind"] == "rate_limited"
    assert run.result["attempts"] == 2 * (waits_per_model + 1)
    assert run.result["model"] == FALLBACK
    assert "retry-after 2 s: TPM limit 8000" in run.result["error"]
    assert len(run.logged) == run.result["attempts"]


def test_no_switch_when_the_fallback_has_no_budget_left() -> None:
    daily = js_constant(PREPARE_NODE, "DAILY_TOKEN_BUDGET")

    run = run_gateway(
        gateway_request(), lambda _: status_reply(429, "1"), {FALLBACK: {"tokens": daily}}
    )

    assert {body["model"] for body in run.sent} == {PRIMARY}
    assert run.result["error_kind"] == "rate_limited" and run.result["fallback_used"] is False


def test_server_error_switches_to_the_fallback_at_once() -> None:
    run = run_gateway(gateway_request(), [status_reply(503, message="over capacity"), ok_reply()])

    assert [body["model"] for body in run.sent] == [PRIMARY, FALLBACK]
    assert run.result["fallback_reason"] == "server_error" and run.result["ok"] is True


@pytest.mark.parametrize(
    ("reply", "kind", "message"),
    [
        (
            status_reply(401, message="Invalid API Key"),
            "http_error",
            "Groq HTTP 401: Invalid API Key",
        ),
        (status_reply(400, message="json_validate_failed"), "http_error", "Groq HTTP 400"),
        ({"error": {"message": "ECONNRESET"}}, "network", "No response from Groq: ECONNRESET"),
        ({"error": "socket hang up"}, "network", "No response from Groq: socket hang up"),
    ],
)
def test_client_and_network_errors_answer_at_once(
    reply: dict[str, Any], kind: str, message: str
) -> None:
    run = run_gateway(gateway_request(), [reply])

    assert (run.result["error_kind"], run.result["attempts"]) == (kind, 1)
    assert message in run.result["error"]
    assert run.logged[0]["status"] == reply.get("statusCode", 0)


def test_5xx_on_the_fallback_model_is_an_error() -> None:
    run = run_gateway(gateway_request(model=FALLBACK), [status_reply(502, message="bad gateway")])

    assert run.result["error_kind"] == "http_error" and run.result["attempts"] == 1


def reply_with_content(content: str, finish_reason: str = "stop") -> dict[str, Any]:
    reply = ok_reply(finish_reason=finish_reason)
    reply["body"]["choices"][0]["message"]["content"] = content
    return reply


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ({"statusCode": 200, "body": {}}, "the reply has no choices"),
        (ok_reply(finish_reason="length"), "finish_reason=length"),
        (reply_with_content("{not json"), "not JSON"),
        (
            reply_with_content('{"eligible": "yes", "score": 1, "groups": null}'),
            "$.eligible should be boolean, got string",
        ),
        (
            reply_with_content('{"eligible": true, "score": 7.5, "groups": null}'),
            "$.score should be integer or null, got number",
        ),
        (reply_with_content('{"eligible": true, "score": 1}'), "$.groups is missing"),
        (
            reply_with_content('{"eligible": true, "score": 1, "groups": null, "x": 1}'),
            "$.x is not allowed",
        ),
        (
            reply_with_content('{"eligible": true, "score": 1, "groups": ["Student"]}'),
            "$.groups[0] is not one of the allowed values",
        ),
        (reply_with_content("[1, 2]"), "$ should be object, got array"),
    ],
)
def test_replies_that_break_the_schema_are_rejected_not_retried(
    reply: dict[str, Any], message: str
) -> None:
    run = run_gateway(gateway_request(), [reply])

    assert run.result["ok"] is False and run.result["data"] is None
    assert run.result["error_kind"] == "invalid_reply"
    assert message in run.result["error"]
    assert run.result["attempts"] == 1 and run.waits == []


def test_schema_errors_are_capped_and_the_error_text_is_clipped() -> None:
    many = {"eligible": 1, "score": "a", "groups": 3, "a": 1, "b": 2, "c": 3}

    run = run_gateway(gateway_request(), [reply_with_content(str(many).replace("'", '"'))])

    listed = run.result["error"].split(": it does not match the schema: ")[1]
    assert len(listed.split("; ")) == js_constant(READ_NODE, "MAX_SCHEMA_ERRORS")
    assert len(run.result["error"]) <= js_constant(READ_NODE, "MAX_ERROR_CHARS")
