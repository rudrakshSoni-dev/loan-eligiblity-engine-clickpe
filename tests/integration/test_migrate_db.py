"""db/migrate.py on real PostgreSQL 16: re-runs are no-ops, drift is refused, seed is flagged.

Needs a superuser connection (e.g. a throwaway `postgres:16` container):
    TEST_DB_HOST=localhost TEST_DB_PORT=55432 TEST_DB_USER=postgres TEST_DB_PASSWORD=... pytest
Each test run creates and drops its own database, so it never touches real data.
"""

import json
import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from pg8000.exceptions import DatabaseError

from db.migrate import (
    DbSettings,
    Migration,
    MigrationError,
    connect,
    load_migrations,
    main,
    migrate,
)

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set")


def admin_settings(database: str) -> DbSettings:
    return DbSettings(
        host=os.environ["TEST_DB_HOST"],
        port=int(os.environ.get("TEST_DB_PORT", "5432")),
        database=database,
        user=os.environ.get("TEST_DB_USER", "postgres"),
        password=os.environ.get("TEST_DB_PASSWORD", ""),
        sslrootcert=None,
    )


@pytest.fixture
def db_env() -> Iterator[dict[str, str]]:
    name = f"migrate_test_{uuid.uuid4().hex[:12]}"
    admin = connect(admin_settings("postgres"))
    admin.run(f'CREATE DATABASE "{name}"')
    s = admin_settings(name)
    yield {
        "DB_HOST": s.host,
        "DB_PORT": str(s.port),
        "DB_NAME": name,
        "DB_USER": s.user,
        "DB_PASSWORD": s.password,
    }
    admin.run(f'DROP DATABASE "{name}" WITH (FORCE)')
    admin.close()


@pytest.fixture
def conn(db_env: dict[str, str]) -> Iterator[Any]:
    c = connect(admin_settings(db_env["DB_NAME"]))
    yield c
    c.close()


def test_second_run_applies_nothing_and_seed_changes_nothing(
    db_env: dict[str, str], conn: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="migrate")
    assert main(["--seed"], env=db_env) == 0
    assert main(["--seed"], env=db_env) == 0

    done = [
        (e["stage"], e["count"])
        for e in (json.loads(r.getMessage()) for r in caplog.records)
        if e["stage"] in {"migrations_done", "seed_done"}
    ]
    # First run: 1 migration, 5 seed rows. Second run: nothing at all.
    assert done == [
        ("migrations_done", 1),
        ("seed_done", 5),
        ("migrations_done", 0),
        ("seed_done", 0),
    ]

    assert conn.run("SELECT version FROM schema_migrations") == [["0001_schema"]]
    tables = conn.run(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
    )
    assert tables == [[11]]  # 10 schema tables + schema_migrations


def test_seed_rows_are_flagged_and_hashed(db_env: dict[str, str], conn: Any) -> None:
    assert main(["--seed"], env=db_env) == 0
    rows = conn.run(
        "SELECT count(*), bool_and(is_seed), bool_and(source = 'seed'),"
        " bool_and(product_name LIKE 'Seed · %'), bool_and(raw_criteria_text LIKE 'SEED DATA.%'),"
        " bool_and(content_hash = encode(sha256(convert_to(raw_criteria_text, 'UTF8')), 'hex'))"
        " FROM loan_products"
    )
    assert rows == [[5, True, True, True, True, True]]


def test_seed_never_rewrites_a_crawled_product(db_env: dict[str, str], conn: Any) -> None:
    assert main([], env=db_env) == 0
    conn.run(
        "INSERT INTO loan_products (source, product_name, min_credit_score, is_seed)"
        " VALUES ('seed', 'Seed · Salaried Personal Loan', 900, false)"
    )
    assert main(["--seed"], env=db_env) == 0
    assert conn.run(
        "SELECT min_credit_score, is_seed FROM loan_products"
        " WHERE product_name = 'Seed · Salaried Personal Loan'"
    ) == [[900, False]]


def test_edited_migration_is_refused_and_nothing_changes(db_env: dict[str, str], conn: Any) -> None:
    assert main([], env=db_env) == 0
    edited = [Migration(m.version, m.sql + "\n-- edited") for m in load_migrations()]
    with pytest.raises(MigrationError, match="edited after it was applied"):
        migrate(conn, edited)
    assert conn.run("SELECT count(*) FROM schema_migrations") == [[1]]


def test_failed_migration_rolls_back_completely(db_env: dict[str, str], conn: Any) -> None:
    broken = [*load_migrations(), Migration("0002_broken", "CREATE TABLE ok_t (id int); SELEC 1;")]
    with pytest.raises(DatabaseError, match="syntax error"):
        migrate(conn, broken)
    # 0001 and the half-done 0002 shared one transaction, so neither left anything behind.
    assert conn.run("SELECT to_regclass('users'), to_regclass('schema_migrations')") == [
        [None, None]
    ]
