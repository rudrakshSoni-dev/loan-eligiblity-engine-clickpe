"""n8n notification: request shape, retry policy and failure reporting, over real local HTTP."""

import json
import socket
import uuid

from lambdas.shared.config import WebhookConfig
from lambdas.shared.notify import (
    RETRY_DELAYS_SECONDS,
    SECRET_HEADER,
    NotifyResult,
    build_request,
    notify_batch_processed,
)
from tests.webhook_helpers import RecordingSender, webhook_receiver

BATCH = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
SECRET = "example-secret"


def notify(url: str, sleeps: list[float], timeout: float = 2.0) -> NotifyResult:
    return notify_batch_processed(
        WebhookConfig(url, SECRET), BATCH, sleep=sleeps.append, timeout=timeout
    )


def closed_port_url() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}/webhook/match-batch"


def test_a_2xx_is_delivered_once_with_the_secret_header_and_the_batch_id() -> None:
    sleeps: list[float] = []
    with webhook_receiver() as n8n:
        result = notify(n8n.url, sleeps)

    assert result == NotifyResult(delivered=True, attempts=1, status=200, error=None)
    assert sleeps == []
    [received] = n8n.received
    assert received.path == "/webhook/match-batch"
    assert received.headers[SECRET_HEADER] == SECRET
    assert received.headers["Content-Type"] == "application/json"
    assert received.body == {"batch_id": str(BATCH)}


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
    assert sender.batch_ids() == [str(BATCH)] * 3


def test_build_request_is_a_json_post() -> None:
    request = build_request(WebhookConfig("http://n8n/webhook/x", SECRET), BATCH)

    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"batch_id": str(BATCH)}  # type: ignore[arg-type]
    assert request.get_header(SECRET_HEADER.capitalize()) == SECRET
