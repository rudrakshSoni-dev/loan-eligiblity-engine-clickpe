"""batch-status handler and status queries: routing, validation, document shape, DB failure."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pg8000.exceptions import InterfaceError

from lambdas.batch_status import handler as module
from lambdas.shared import status
from lambdas.shared.config import BatchStatusConfig, ConfigError, DbConfig
from lambdas.shared.db import Database

DB_CONFIG = DbConfig("db", 5432, "loans", "user", "pw", ca_bundle=None)
BATCH_ID = uuid.uuid4()
CREATED = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
UPDATED = datetime(2026, 10, 21, 9, 5, tzinfo=UTC)
BATCH_ROW = ["loading", None, 4, 1, 5000, 3, CREATED, UPDATED]


class FakeConnection:
    def __init__(
        self,
        batch: list[Any] | None = BATCH_ROW,
        funnel: list[Any] | None = None,
        fail: bool = False,
    ) -> None:
        self.batch = batch
        self.funnel = funnel
        self.fail = fail
        self.closed = False
        self.queries: list[tuple[str, dict[str, Any]]] = []

    def run(self, sql: str, **params: Any) -> list[list[Any]]:
        if self.fail:
            raise InterfaceError("connection is closed")
        self.queries.append((sql, params))
        if sql == status.BATCH_SQL:
            return [self.batch] if self.batch else []
        if sql == status.REJECTS_SQL:
            return [[2, "age out of range"], [7, "bad email"]]
        if sql == status.MATCHES_SQL:
            return [[10, 4]]
        if sql == status.FUNNEL_SQL:
            return [self.funnel] if self.funnel else []
        raise AssertionError(sql)

    def close(self) -> None:
        self.closed = True


def install_runtime(monkeypatch: pytest.MonkeyPatch, conn: FakeConnection) -> None:
    app = module.Runtime(
        BatchStatusConfig(DB_CONFIG), Database(DB_CONFIG, connector=lambda _config: conn)
    )
    monkeypatch.setattr(module, "runtime", lambda: app)


def get_event(batch_id: str | None = str(BATCH_ID), method: str = "GET") -> dict[str, Any]:
    event: dict[str, Any] = {"requestContext": {"http": {"method": method}}}
    if batch_id is not None:
        event["queryStringParameters"] = {"batch_id": batch_id}
    return event


def test_known_batch_returns_progress_without_a_funnel(monkeypatch: pytest.MonkeyPatch) -> None:
    install_runtime(monkeypatch, FakeConnection())

    response = module.handler(get_event(), None)

    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert response["headers"]["cache-control"] == "no-store"
    assert body == {
        "batch_id": str(BATCH_ID),
        "status": "loading",
        "error": None,
        "total_chunks": 4,
        "chunks_done": 1,
        "rows_ok": 5000,
        "rows_rejected": 3,
        "first_rejects": [
            {"line_no": 2, "reason": "age out of range"},
            {"line_no": 7, "reason": "bad email"},
        ],
        "matches": 10,
        "notified": 4,
        "funnel": None,
        "created_at": CREATED.isoformat(),
        "updated_at": UPDATED.isoformat(),
    }


def test_funnel_is_passed_through_with_unmeasured_counters_as_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    measured = {
        "total_pairs": 500,
        "stage1_pairs": 200,
        "stage1_near_miss": 90,
        "stage2_clear": 100,
        "stage2_borderline": 80,
        "stage2_reject": 20,
        "stage_ms": {},
        "started_at": CREATED,
    }
    funnel_row: list[Any] = [measured.get(column) for column in status.FUNNEL_COLUMNS]
    install_runtime(monkeypatch, FakeConnection(funnel=funnel_row))

    body = json.loads(module.handler(get_event(), None)["body"])

    assert set(body["funnel"]) == set(status.FUNNEL_COLUMNS)
    assert body["funnel"]["total_pairs"] == 500
    assert body["funnel"]["stage1_near_miss"] == 90
    assert body["funnel"]["stage2_reject"] == 20
    assert body["funnel"]["llm_calls"] is None
    assert body["funnel"]["stage3_eligible"] is None
    assert body["funnel"]["started_at"] == CREATED.isoformat()
    assert body["funnel"]["finished_at"] is None


def test_reject_preview_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection()
    install_runtime(monkeypatch, conn)

    module.handler(get_event(), None)

    limits = [p["limit"] for sql, p in conn.queries if sql == status.REJECTS_SQL]
    assert limits == [5]


def test_unknown_batch_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    install_runtime(monkeypatch, FakeConnection(batch=None))
    response = module.handler(get_event(), None)
    assert response["statusCode"] == 404
    assert json.loads(response["body"]) == {"error": "unknown batch_id"}


@pytest.mark.parametrize("raw", [None, "", "not-a-uuid", "123"])
def test_missing_or_malformed_batch_id_is_400_and_queries_nothing(
    monkeypatch: pytest.MonkeyPatch, raw: str | None
) -> None:
    conn = FakeConnection()
    install_runtime(monkeypatch, conn)

    response = module.handler(get_event(raw), None)

    assert response["statusCode"] == 400
    assert conn.queries == []


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", ""])
def test_other_methods_get_405(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    conn = FakeConnection()
    install_runtime(monkeypatch, conn)

    assert module.handler(get_event(method=method), None)["statusCode"] == 405
    assert conn.queries == []


def test_database_failure_returns_503_and_drops_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection(fail=True)
    install_runtime(monkeypatch, conn)

    response = module.handler(get_event(), None)

    assert response["statusCode"] == 503
    assert json.loads(response["body"]) == {"error": "database unavailable"}


def test_runtime_fails_loudly_on_missing_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    module.runtime.cache_clear()
    with pytest.raises(ConfigError, match="DB_HOST is missing"):
        module.runtime()
    module.runtime.cache_clear()


def test_runtime_is_built_once_and_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {"DB_HOST": "db.internal", "DB_NAME": "loans", "DB_USER": "u", "DB_PASSWORD": "pw"}
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    module.runtime.cache_clear()

    first = module.runtime()

    assert first is module.runtime()
    assert first.config.db.host == "db.internal"
    module.runtime.cache_clear()
