"""Least-privilege database roles: `app_ingest` for the Lambdas, `app_n8n` for the workflows.

Each role is checked three ways on PostgreSQL 16. The exact table privileges are compared with the
list in this file, so a broader grant fails as surely as a missing one. Every SQL statement in the
exported workflows is planned as `app_n8n` with `EXPLAIN (GENERIC_PLAN)`, which runs the permission
checks without executing anything, so failure branches that a normal run never reaches are covered
too. The Lambda path (create, COPY into a temp table, upsert, rejects, completion, failure, status)
runs for real as `app_ingest`.
"""

import json
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pg8000.exceptions import DatabaseError

from lambdas.load_chunk import handler as module
from lambdas.shared.batches import create_batch, upload_key
from lambdas.shared.chunks import SplitFailure, encode_message
from lambdas.shared.config import DbConfig, LoadChunkConfig, WebhookConfig
from lambdas.shared.db import Database
from lambdas.shared.reject_report import download
from lambdas.shared.status import batch_status
from tests.chunk_helpers import BUCKET, FakeS3, line_chunks
from tests.webhook_helpers import RecordingSender

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set")

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((REPO / "n8n" / "workflows").glob("*.json"))
FIXTURES = REPO / "tests" / "fixtures"
UNUSED_DB_CONFIG = DbConfig("unused", 5432, "unused", "unused", "unused", ca_bundle=None)
CONFIG = LoadChunkConfig(
    UNUSED_DB_CONFIG, BUCKET, WebhookConfig("http://n8n.invalid/", "example-signing-key-0123456789")
)
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
READ_WRITE = {"SELECT", "INSERT", "UPDATE"}
APPEND = {"SELECT", "INSERT"}
EXPECTED: dict[str, dict[str, set[str]]] = {
    "app_ingest": {
        "upload_batches": READ_WRITE,
        "chunk_loads": READ_WRITE,
        "users": READ_WRITE,
        "rejected_rows": APPEND,
        "matches": {"SELECT"},
        "pipeline_runs": {"SELECT"},
    },
    "app_n8n": {
        "upload_batches": {"SELECT", "UPDATE"},
        "users": {"SELECT"},
        "app_config": {"SELECT"},
        "loan_products": READ_WRITE,
        "pipeline_runs": READ_WRITE,
        "match_candidates": READ_WRITE,
        "matches": READ_WRITE,
        "n8n_errors": READ_WRITE,
        "crawl_runs": APPEND,
        "cohort_verdicts": APPEND,
        "llm_calls": APPEND,
    },
}


def as_role(conn: Any, role: str) -> Any:
    conn.run(f"SET ROLE {role}")
    return conn


def workflow_statements() -> list[Any]:
    found = []
    for path in WORKFLOWS:
        for node in json.loads(path.read_text(encoding="utf-8"))[0]["nodes"]:
            query = node["parameters"].get("query")
            if node["type"] == "n8n-nodes-base.postgres" and query:
                found.append(pytest.param(query, id=f"{path.stem} / {node['name']}"))
    return found


def is_permission_error(error: DatabaseError) -> bool:
    return isinstance(error.args[0], dict) and error.args[0].get("C") == "42501"


def test_each_role_holds_exactly_the_listed_table_privileges(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    tables = [r[0] for r in conn.run("SELECT tablename FROM pg_tables WHERE schemaname='public'")]
    for role, expected in EXPECTED.items():
        held = {
            table: {
                p
                for p in PRIVILEGES
                if conn.run(f"SELECT has_table_privilege('{role}', 'public.{table}', '{p}')")[0][0]
            }
            for table in tables
        }
        assert {t: p for t, p in held.items() if p} == expected, role


def test_roles_cannot_create_objects_or_roles_and_have_connection_limits(
    connect_db: Callable[[], Any],
) -> None:
    conn = connect_db()
    attributes = conn.run(
        "SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls, rolconnlimit"
        " FROM pg_roles WHERE rolname IN ('app_ingest', 'app_n8n') ORDER BY rolname"
    )
    assert attributes == [
        ["app_ingest", False, False, False, False, 10],
        ["app_n8n", False, False, False, False, 20],
    ]
    for role, statement in [
        ("app_ingest", "CREATE TABLE public.intruder (id int)"),
        ("app_n8n", "CREATE TABLE public.intruder (id int)"),
        ("app_n8n", "CREATE ROLE intruder"),
        ("app_n8n", "DELETE FROM users"),
        ("app_n8n", "TRUNCATE match_candidates"),
        ("app_ingest", "SELECT count(*) FROM loan_products"),
        ("app_ingest", "SELECT count(*) FROM app_config"),
        ("app_ingest", "DELETE FROM users"),
    ]:
        role_conn = as_role(connect_db(), role)
        with pytest.raises(DatabaseError) as refused:
            role_conn.run(statement)
        assert is_permission_error(refused.value), (role, statement, refused.value)


@pytest.mark.parametrize("query", workflow_statements())
def test_every_exported_workflow_statement_is_permitted_for_app_n8n(
    connect_db: Callable[[], Any], query: str
) -> None:
    conn = as_role(connect_db(), "app_n8n")
    for statement in (s.strip() for s in query.split(";")):
        if statement:
            conn.run(f"EXPLAIN (GENERIC_PLAN) {statement}")


def test_the_planning_check_does_catch_a_missing_privilege(connect_db: Callable[[], Any]) -> None:
    conn = as_role(connect_db(), "app_ingest")
    with pytest.raises(DatabaseError) as refused:
        conn.run("EXPLAIN (GENERIC_PLAN) UPDATE loan_products SET active = $1 WHERE id = $2")
    assert is_permission_error(refused.value)


def test_app_n8n_refreshes_statistics_only_through_the_definer_function(
    connect_db: Callable[[], Any],
) -> None:
    conn = as_role(connect_db(), "app_n8n")
    last_analyze = (
        "SELECT last_analyze IS NOT NULL FROM pg_stat_user_tables"
        " WHERE relname = 'match_candidates'"
    )
    conn.run("ANALYZE match_candidates")
    assert conn.run(last_analyze) == [[False]]
    conn.run("SELECT analyze_match_candidates()")
    assert conn.run(last_analyze) == [[True]]
    with pytest.raises(DatabaseError) as refused:
        as_role(connect_db(), "app_ingest").run("SELECT analyze_match_candidates()")
    assert is_permission_error(refused.value)


def test_the_lambda_path_runs_end_to_end_as_app_ingest(
    connect_db: Callable[[], Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest = as_role(connect_db(), "app_ingest")
    s3 = FakeS3()
    database = Database(UNUSED_DB_CONFIG, lambda _c: as_role(connect_db(), "app_ingest"))
    app = module.Runtime(CONFIG, database, s3, RecordingSender())
    monkeypatch.setattr(module, "runtime", lambda: app)

    def deliver(*messages: Any) -> Any:
        records = [
            {"messageId": f"m{i}", "body": encode_message(m)} for i, m in enumerate(messages)
        ]
        return module.handler({"Records": records}, None)["batchItemFailures"]

    loaded = []
    for name in ("good_users.csv", "malformed_users.csv"):
        data = (FIXTURES / name).read_bytes()
        batch_id = create_batch(ingest)
        chunks = line_chunks(data, batch_id, s3.put(upload_key(batch_id), data), 3)
        assert deliver(*chunks, *chunks) == []
        loaded.append(batch_id)
    failed = create_batch(ingest)
    assert deliver(SplitFailure(failed, "bad header")) == []

    good, malformed = (batch_status(ingest, b) for b in loaded)
    assert good is not None and malformed is not None
    assert (good["status"], good["rows_rejected"]) == ("processed", 0)
    assert (malformed["status"], malformed["rows_ok"], malformed["rows_rejected"]) == (
        "processed",
        1,
        10,
    )
    assert (batch_status(ingest, failed) or {})["status"] == "failed"
    assert (download(ingest, loaded[1]) or "").count("\n") == 11
    assert batch_status(ingest, uuid.uuid4()) is None
