"""Migration planning rules that need no database: ordering, re-run skip, drift refusal."""

from pathlib import Path

import pytest

from db.migrate import (
    MIGRATIONS,
    Migration,
    MigrationError,
    load_migrations,
    pending_migrations,
    settings_from_env,
)

FIRST = Migration("0001_a", "CREATE TABLE a (id int);")
SECOND = Migration("0002_b", "CREATE TABLE b (id int);")

DB_ENV = {"DB_HOST": "h", "DB_NAME": "n", "DB_USER": "u", "DB_PASSWORD": "p"}


def test_fresh_database_gets_every_migration_in_order() -> None:
    assert pending_migrations([FIRST, SECOND], {}) == [FIRST, SECOND]


def test_applied_migrations_are_skipped() -> None:
    assert pending_migrations([FIRST, SECOND], {FIRST.version: FIRST.checksum}) == [SECOND]


def test_fully_migrated_database_has_nothing_pending() -> None:
    applied = {m.version: m.checksum for m in (FIRST, SECOND)}
    assert pending_migrations([FIRST, SECOND], applied) == []


def test_edited_applied_migration_is_refused() -> None:
    edited = Migration(FIRST.version, FIRST.sql + " SELECT 1;")
    with pytest.raises(MigrationError, match="edited after it was applied"):
        pending_migrations([edited, SECOND], {FIRST.version: FIRST.checksum})


def test_database_ahead_of_code_is_refused() -> None:
    with pytest.raises(MigrationError, match="does not know"):
        pending_migrations([FIRST], {"0099_future": "0" * 64})


def test_checksum_is_sha256_hex_of_the_file_text() -> None:
    assert FIRST.checksum == Migration("other", FIRST.sql).checksum
    assert len(FIRST.checksum) == 64
    assert FIRST.checksum != SECOND.checksum


def test_registered_migration_files_exist_and_have_unique_versions() -> None:
    versions = [version for version, _ in MIGRATIONS]
    assert versions == sorted(set(versions))
    assert all(sql.strip() for sql in (m.sql for m in load_migrations()))


def test_migration_files_leave_the_transaction_to_the_runner() -> None:
    """An inner COMMIT would end the runner's transaction before the ledger row is written.

    Only "BEGIN;" is refused: a plpgsql block opener ("BEGIN" with no semicolon) is fine.
    """
    for _, path in MIGRATIONS:
        lines = {line.strip().upper() for line in Path(path).read_text().splitlines()}
        assert not lines & {"BEGIN;", "COMMIT;", "ROLLBACK;"}, path


def test_settings_require_connection_variables() -> None:
    with pytest.raises(MigrationError, match="DB_HOST, DB_PASSWORD"):
        settings_from_env({"DB_NAME": "n", "DB_USER": "u"})


def test_settings_defaults_and_optional_tls() -> None:
    plain = settings_from_env(DB_ENV)
    assert (plain.port, plain.sslrootcert) == (5432, None)
    tls = settings_from_env({**DB_ENV, "DB_PORT": "6543", "DB_SSLROOTCERT": "/ca.pem"})
    assert (tls.port, tls.sslrootcert) == (6543, "/ca.pem")
