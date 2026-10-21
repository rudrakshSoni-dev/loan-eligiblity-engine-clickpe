"""n8n notification: request shape, retry policy and failure reporting, over real local HTTP."""

import json
import socket
import uuid

import pytest

from lambdas.shared.config import WebhookConfig
from lambdas.shared.notify import (
    AUTH_HEADER,
    RETRY_DELAYS_SECONDS,
    TIMEOUT_SECONDS,
    TOKEN_ISSUER,
    TOKEN_TTL_SECONDS,
    NotifyResult,
    build_request,
    notify_batch_processed,
    signed_token,
)
from tests.webhook_helpers import RecordingSender, token_claims, webhook_receiver

BATCH = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
OTHER_BATCH = uuid.UUID("00000000-0000-4000-8000-0000000000bb")
SECRET = "example-signing-key-0123456789abcdef"
NOW = 1_792_000_000


def notify(url: str, sleeps: list[float], timeout: float = 2.0) -> NotifyResult:
    return notify_batch_processed(
        WebhookConfig(url, SECRET),
        BATCH,
        sleep=sleeps.append,
        timeout=timeout,
        clock=lambda: NOW + 0.9,
    )


def closed_port_url() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}/webhook/match-batch"


def test_a_2xx_is_delivered_once_with_a_signed_token_and_the_batch_id() -> None:
    sleeps: list[float] = []
    with webhook_receiver() as n8n:
        result = notify(n8n.url, sleeps)

    assert result == NotifyResult(delivered=True, attempts=1, status=200, error=None)
    assert sleeps == []
    [received] = n8n.received
    assert received.path == "/webhook/match-batch"
    assert token_claims(received.headers[AUTH_HEADER], SECRET) == {
        "iss": TOKEN_ISSUER,
        "batch_id": str(BATCH),
        "iat": NOW,
        "exp": NOW + TOKEN_TTL_SECONDS,
    }
    assert received.headers["Content-Type"] == "application/json"
    assert received.body == {"batch_id": str(BATCH)}
    assert all(SECRET not in value for value in received.headers.values())


def test_a_5xx_is_retried_with_backoff_until_it_succeeds() -> None:
    sleeps: list[float] = []
    with webhook_receiver() as n8n:
        n8n.statuses.extend([503, 502])
        result = notify(n8n.url, sleeps)

    assert result == NotifyResult(delivered=True, attempts=3, status=200, error=None)
    assert sleeps == list(RETRY_DELAYS_SECONDS)
    assert n8n.batch_ids() == [str(BATCH)] * 3


def test_retries_stop_after_three_attempts_and_report_the_last_status() -> None:
    sleeps: list[float] = []
    with webhook_receiver() as n8n:
        n8n.statuses.extend([500, 429, 503, 200])
        result = notify(n8n.url, sleeps)

    assert result == NotifyResult(delivered=False, attempts=3, status=503, error=None)
    assert len(n8n.received) == 3


def test_a_refusal_is_not_retried() -> None:
    for refused in (401, 403, 404):
        sleeps: list[float] = []
        with webhook_receiver() as n8n:
            n8n.statuses.append(refused)
            result = notify(n8n.url, sleeps)

        assert result == NotifyResult(delivered=False, attempts=1, status=refused, error=None)
        assert sleeps == []
        assert len(n8n.received) == 1


def test_an_unreachable_n8n_is_retried_and_reported_without_raising() -> None:
    sleeps: list[float] = []
    result = notify(closed_port_url(), sleeps)

    assert not result.delivered
    assert result.attempts == 3
    assert result.status is None
    assert result.error is not None
    assert "Connection refused" in result.error
    assert sleeps == list(RETRY_DELAYS_SECONDS)


def test_a_slow_n8n_times_out_and_the_next_attempt_succeeds() -> None:
    sleeps: list[float] = []
    with webhook_receiver() as n8n:
        n8n.delay_seconds.append(1.0)
        result = notify(n8n.url, sleeps, timeout=0.2)

    assert result == NotifyResult(delivered=True, attempts=2, status=200, error=None)
    assert len(n8n.received) == 2


def test_a_timeout_on_every_attempt_is_reported_as_an_error() -> None:
    sleeps: list[float] = []
    with webhook_receiver() as n8n:
        n8n.delay_seconds.extend([1.0, 1.0, 1.0])
        result = notify(n8n.url, sleeps, timeout=0.2)

    assert not result.delivered
    assert result.attempts == 3
    assert result.error is not None
    assert "timed out" in result.error


def test_the_secret_never_appears_in_the_result_or_the_request_repr() -> None:
    sender = RecordingSender(statuses=[503, 503, 503])
    result = notify_batch_processed(
        WebhookConfig("http://n8n.invalid/webhook/match-batch", SECRET),
        BATCH,
        send=sender,
        sleep=lambda _s: None,
    )

    assert SECRET not in repr(result)
    assert SECRET not in repr(sender.requests[0])
    assert all(SECRET not in value for value in sender.requests[0].headers.values())
    assert sender.batch_ids() == [str(BATCH)] * 3


def test_build_request_is_a_json_post_with_a_bearer_token() -> None:
    request = build_request(WebhookConfig("http://n8n/webhook/x", SECRET), BATCH, NOW)

    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"batch_id": str(BATCH)}  # type: ignore[arg-type]
    claims = token_claims(str(request.get_header(AUTH_HEADER)), SECRET)
    assert (claims["batch_id"], claims["exp"]) == (str(BATCH), NOW + TOKEN_TTL_SECONDS)


def test_one_token_serves_every_attempt_and_outlives_the_worst_case_retry_loop() -> None:
    sender = RecordingSender(statuses=[503, 502, 200])
    result = notify_batch_processed(
        WebhookConfig("http://n8n.invalid/webhook/match-batch", SECRET),
        BATCH,
        send=sender,
        sleep=lambda _s: None,
        clock=lambda: NOW,
    )

    assert result.delivered
    assert len({r.get_header(AUTH_HEADER) for r in sender.requests}) == 1
    attempts = 1 + len(RETRY_DELAYS_SECONDS)
    assert attempts * TIMEOUT_SECONDS + sum(RETRY_DELAYS_SECONDS) < TOKEN_TTL_SECONDS


def test_the_token_is_bound_to_its_batch_and_to_the_signing_key() -> None:
    token = signed_token(SECRET, BATCH, NOW)

    assert token_claims(f"Bearer {token}", SECRET)["batch_id"] == str(BATCH)
    assert token_claims(f"Bearer {signed_token(SECRET, OTHER_BATCH, NOW)}", SECRET)[
        "batch_id"
    ] == str(OTHER_BATCH)
    with pytest.raises(AssertionError):
        token_claims(f"Bearer {token}", SECRET + "x")
    header, _claims, signature = token.split(".")
    forged_claims = signed_token(SECRET, OTHER_BATCH, NOW).split(".")[1]
    with pytest.raises(AssertionError):
        token_claims(f"Bearer {header}.{forged_claims}.{signature}", SECRET)
    assert SECRET not in token
    assert not set(token) & set("+/=")
