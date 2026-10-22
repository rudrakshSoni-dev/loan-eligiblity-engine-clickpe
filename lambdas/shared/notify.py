"""Tell n8n that a batch finished loading: one POST of {"batch_id"} with a 60-second signed token.

The request carries `Authorization: Bearer <JWT>`, an HS256 token signed with the shared secret and
bound to the batch id, instead of the secret itself. n8n's Webhook node saves request headers in
every execution, so a plain secret header would sit in its database; a token stored there has
expired a minute later, names one batch that Workflow B has already claimed, and never reveals the
signing key. The token is built with the standard library (RFC 7519, HS256 only).

Called only by the load-chunk invocation whose conditional loading → processed UPDATE returned a
row, so each batch is announced once. Delivery is bounded (5 s per attempt, 3 attempts) and never
raises: a failure is returned to the caller, which logs it and leaves the batch `processed` for
scripts/retrigger_batch.sh. Only network errors, timeouts, 429 and 5xx are retried; any other
status (401 no token, 403 allowlist or bad token, 404 workflow not published) cannot improve
within seconds.
Uses the standard library, so the Lambda package gains no dependency.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from lambdas.shared.config import WebhookConfig

AUTH_HEADER = "Authorization"
TOKEN_ISSUER = "clickpe-load-chunk"
TOKEN_TTL_SECONDS = 60
TIMEOUT_SECONDS = 5.0
RETRY_DELAYS_SECONDS = (0.5, 1.0)
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

Sender = Callable[[urllib.request.Request, float], int]


@dataclass(frozen=True)
class NotifyResult:
    """Outcome of announcing a batch: delivered or not, attempts, last status/error."""

    delivered: bool
    attempts: int
    status: int | None
    error: str | None


def _base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _compact_json(value: dict[str, object]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def signed_token(secret: str, batch_id: uuid.UUID, issued_at: int) -> str:
    """Return an HS256 JWT naming `batch_id` that expires TOKEN_TTL_SECONDS after `issued_at`."""
    header = _base64url(_compact_json({"alg": "HS256", "typ": "JWT"}))
    claims = {
        "iss": TOKEN_ISSUER,
        "batch_id": str(batch_id),
        "iat": issued_at,
        "exp": issued_at + TOKEN_TTL_SECONDS,
    }
    signing_input = f"{header}.{_base64url(_compact_json(claims))}"
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_base64url(signature)}"


def build_request(
    webhook: WebhookConfig, batch_id: uuid.UUID, issued_at: int
) -> urllib.request.Request:
    """Build the POST of `{batch_id}` with a freshly signed bearer token."""
    token = signed_token(webhook.secret, batch_id, issued_at)
    return urllib.request.Request(
        webhook.url,
        data=json.dumps({"batch_id": str(batch_id)}).encode(),
        headers={"Content-Type": "application/json", AUTH_HEADER: f"Bearer {token}"},
        method="POST",
    )


def send_request(request: urllib.request.Request, timeout: float) -> int:
    """POST and return the HTTP status; an error status is returned, not raised."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)


def notify_batch_processed(
    webhook: WebhookConfig,
    batch_id: uuid.UUID,
    send: Sender = send_request,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = TIMEOUT_SECONDS,
    clock: Callable[[], float] = time.time,
) -> NotifyResult:
    """POST the batch id to n8n, retrying transient failures; True in `delivered` on any 2xx.

    One token serves every attempt: three 5-second attempts and 1.5 s of back-off end well inside
    its 60-second lifetime.
    """
    request = build_request(webhook, batch_id, int(clock()))
    status: int | None = None
    error: str | None = None
    attempts = 0
    for delay in (0.0, *RETRY_DELAYS_SECONDS):
        if delay:
            sleep(delay)
        attempts += 1
        try:
            status, error = send(request, timeout), None
        except (OSError, http.client.HTTPException) as failure:
            status, error = None, f"{type(failure).__name__}: {failure}"
            continue
        if 200 <= status < 300:
            return NotifyResult(True, attempts, status, None)
        if status not in RETRYABLE_STATUSES:
            break
    return NotifyResult(False, attempts, status, error)
