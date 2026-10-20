"""get-upload-url handler: routing, success body, database failure, with a scripted connection."""

import json
import uuid
from typing import Any

import pytest
from pg8000.exceptions import InterfaceError

from lambdas.get_upload_url import handler as module
from lambdas.shared.config import ConfigError, DbConfig, UploadUrlConfig
from lambdas.shared.db import Database
from lambdas.shared.uploads import PRESIGN_EXPIRY_SECONDS

BUCKET = "clickpe-loan-uploads-test"
MAX_BYTES = 1024
DB_CONFIG = DbConfig("db", 5432, "loans", "user", "pw", ca_bundle=None)


class FakeConnection:
    def __init__(self, fail_on_insert: bool = False) -> None:
        self.fail_on_insert = fail_on_insert
        self.inserts: list[dict[str, Any]] = []
        self.closed = False

    def run(self, sql: str, **params: Any) -> list[list[Any]]:
        if sql.startswith("INSERT"):
            if self.fail_on_insert:
                raise InterfaceError("connection is closed")
            self.inserts.append(params)
        return []

    def close(self) -> None:
        self.closed = True


class FakeSigner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_presigned_post(
        self,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        Fields: dict[str, str],  # noqa: N803
        Conditions: list[Any],  # noqa: N803
        ExpiresIn: int,  # noqa: N803
    ) -> dict[str, Any]:
        self.calls.append(
            {"Bucket": Bucket, "Key": Key, "Conditions": Conditions, "ExpiresIn": ExpiresIn}
        )
        return {"url": f"https://{Bucket}.s3.example/", "fields": {"key": Key, **Fields}}


def install_runtime(
    monkeypatch: pytest.MonkeyPatch, conn: FakeConnection
) -> tuple[FakeSigner, Database]:
    signer = FakeSigner()
    database = Database(DB_CONFIG, connector=lambda _config: conn)
    app = module.Runtime(UploadUrlConfig(DB_CONFIG, BUCKET, MAX_BYTES), database, signer)
    monkeypatch.setattr(module, "runtime", lambda: app)
    return signer, database


def post_event(method: str = "POST") -> dict[str, Any]:
    return {"requestContext": {"http": {"method": method}}}


def test_post_creates_a_batch_and_returns_the_signed_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection()
    signer, _ = install_runtime(monkeypatch, conn)

    response = module.handler(post_event(), None)

    body = json.loads(response["body"])
    batch_id = uuid.UUID(body["batch_id"])
    assert response["statusCode"] == 200
    assert response["headers"]["content-type"] == "application/json"
    assert conn.inserts == [{"id": batch_id, "key": f"uploads/{batch_id}.csv"}]
    assert body["upload"]["fields"]["key"] == f"uploads/{batch_id}.csv"
    assert body["max_upload_bytes"] == MAX_BYTES
    assert body["expires_in_seconds"] == PRESIGN_EXPIRY_SECONDS
    assert signer.calls[0]["Bucket"] == BUCKET
    assert signer.calls[0]["Conditions"][1] == ["content-length-range", 1, MAX_BYTES]


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE", ""])
def test_other_methods_get_405_and_touch_nothing(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    conn = FakeConnection()
    signer, _ = install_runtime(monkeypatch, conn)

    response = module.handler(post_event(method), None)

    assert response["statusCode"] == 405
    assert conn.inserts == []
    assert signer.calls == []


def test_event_without_http_context_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    install_runtime(monkeypatch, FakeConnection())
    assert module.handler({}, None)["statusCode"] == 405


def test_database_failure_returns_503_without_a_signed_upload_and_drops_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection(fail_on_insert=True)
    signer, _ = install_runtime(monkeypatch, conn)

    response = module.handler(post_event(), None)

    assert response["statusCode"] == 503
    assert json.loads(response["body"]) == {"error": "database unavailable"}
    assert signer.calls == []
    assert conn.closed


def test_runtime_fails_loudly_on_missing_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "UPLOAD_BUCKET"):
        monkeypatch.delenv(name, raising=False)
    module.runtime.cache_clear()
    with pytest.raises(ConfigError, match="DB_HOST is missing"):
        module.runtime()
    module.runtime.cache_clear()


def test_runtime_is_built_once_and_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        "DB_HOST": "db.internal",
        "DB_NAME": "loans",
        "DB_USER": "loans_app",
        "DB_PASSWORD": "pw",
        "UPLOAD_BUCKET": BUCKET,
        "MAX_UPLOAD_BYTES": "2048",
        "AWS_REGION": "ap-southeast-2",
        "AWS_ACCESS_KEY_ID": "AKIDEXAMPLE",
        "AWS_SECRET_ACCESS_KEY": "example-secret",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    module.runtime.cache_clear()

    first = module.runtime()

    assert first is module.runtime()
    assert first.config.bucket == BUCKET
    assert first.config.max_upload_bytes == 2048
    module.runtime.cache_clear()
