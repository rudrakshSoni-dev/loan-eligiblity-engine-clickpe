"""Test doubles for the n8n webhook: an in-process sender and a real local HTTP receiver.

`RecordingSender` replaces the network for handler tests. `WebhookReceiver` is a real HTTP server on
127.0.0.1, so tests of `send_request` go through urllib and sockets exactly as the Lambda does.
`token_claims` checks a received bearer token with its own HMAC code, not the module under test.
"""

import base64
import hashlib
import hmac
import json
import threading
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class RecordingSender:
    statuses: list[int] = field(default_factory=list)
    requests: list[urllib.request.Request] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __call__(self, request: urllib.request.Request, timeout: float) -> int:
        with self.lock:
            self.requests.append(request)
            return self.statuses.pop(0) if self.statuses else 200

    def batch_ids(self) -> list[str]:
        return [json.loads(r.data)["batch_id"] for r in self.requests]  # type: ignore[arg-type]


def _base64url_decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def token_claims(authorization: str, secret: str) -> dict[str, Any]:
    """Verify a `Bearer` HS256 token and return its claims; AssertionError if it is forged."""
    scheme, token = authorization.split(" ")
    assert scheme == "Bearer"
    header_part, claims_part, signature_part = token.split(".")
    assert "=" not in token
    expected = hmac.new(
        secret.encode(), f"{header_part}.{claims_part}".encode(), hashlib.sha256
    ).digest()
    assert hmac.compare_digest(_base64url_decode(signature_part), expected)
    assert json.loads(_base64url_decode(header_part)) == {"alg": "HS256", "typ": "JWT"}
    claims: dict[str, Any] = json.loads(_base64url_decode(claims_part))
    return claims


@dataclass
class Received:
    path: str
    headers: dict[str, str]
    body: dict[str, Any]


@dataclass
class WebhookReceiver:
    url: str
    received: list[Received]
    statuses: list[int]
    delay_seconds: list[float]

    def batch_ids(self) -> list[str]:
        return [r.body["batch_id"] for r in self.received]


def handler_class(receiver: WebhookReceiver, lock: threading.Lock) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            with lock:
                receiver.received.append(
                    Received(self.path, dict(self.headers.items()), json.loads(body))
                )
                status = receiver.statuses.pop(0) if receiver.statuses else 200
                delay = receiver.delay_seconds.pop(0) if receiver.delay_seconds else 0.0
            time.sleep(delay)
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            return None

    return Handler


@contextmanager
def webhook_receiver(path: str = "/webhook/match-batch") -> Iterator[WebhookReceiver]:
    """Run a local HTTP server; queue `statuses` / `delay_seconds` to script its next answers."""
    receiver = WebhookReceiver("", [], [], [])
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class(receiver, threading.Lock()))
    server.daemon_threads = True
    receiver.url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield receiver
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
