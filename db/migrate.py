"""Apply database migrations exactly once each, in order, and optionally the product seed.

Usage (from the repo root):
    uv run python -m db.migrate           applies pending migrations only
    uv run python -m db.migrate --seed    also upserts the seed products afterwards

Connection settings: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, and optional
DB_SSLROOTCERT (path to the RDS CA bundle). With DB_SSLROOTCERT the server certificate and
hostname are verified; without it the connection is plain, which RDS refuses because
rds.force_ssl is on, so there is no silent unencrypted path to RDS.

Every applied file is recorded in schema_migrations with its SHA-256. Re-running is a no-op;
editing a file that was already applied is refused, because the database would no longer
match the file anyone reads in the repo. MIGRATIONS is ordered and append-only: a schema
change is a new entry, never an edit of an old file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import ssl
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pg8000.native
from pg8000.exceptions import DatabaseError, InterfaceError

DB_DIR = Path(__file__).resolve().parent

MIGRATIONS: tuple[tuple[str, Path], ...] = (
    ("0001_schema", DB_DIR / "schema.sql"),
    ("0002_match_candidates", DB_DIR / "0002_match_candidates.sql"),
    ("0003_stage2_rules", DB_DIR / "0003_stage2_rules.sql"),
)

SEED_FILE = DB_DIR / "seed_products.sql"

MIGRATION_LOCK_KEY = 8_420_190_001

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text        PRIMARY KEY,
    checksum   text        NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""

REQUIRED_ENV = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD")

LOG = logging.getLogger("migrate")


class MigrationError(Exception):
    """The database and the migration files disagree; nothing was changed."""


@dataclass(frozen=True)
class Migration:
    version: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DbSettings:
    host: str
    port: int
    database: str
    user: str
    password: str
    sslrootcert: str | None


def log_event(stage: str, **fields: object) -> None:
    LOG.info(json.dumps({"stage": stage, **fields}, default=str))


def load_migrations(entries: Sequence[tuple[str, Path]] = MIGRATIONS) -> list[Migration]:
    return [Migration(version, path.read_text(encoding="utf-8")) for version, path in entries]


def pending_migrations(files: Sequence[Migration], applied: Mapping[str, str]) -> list[Migration]:
    """Return the files not yet applied, after checking the applied ones are unchanged.

    `applied` maps version -> checksum as stored in schema_migrations.
    """
    known = {m.version for m in files}
    unknown = sorted(set(applied) - known)
    if unknown:
        raise MigrationError(f"database has migrations this code does not know: {unknown}")
    for m in files:
        if m.version in applied and applied[m.version] != m.checksum:
            raise MigrationError(
                f"{m.version} was edited after it was applied "
                f"(db {applied[m.version][:12]}…, file {m.checksum[:12]}…); add a new migration"
            )
    return [m for m in files if m.version not in applied]


def settings_from_env(env: Mapping[str, str]) -> DbSettings:
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        raise MigrationError(f"missing environment variables: {', '.join(missing)}")
    return DbSettings(
        host=env["DB_HOST"],
        port=int(env.get("DB_PORT") or "5432"),
        database=env["DB_NAME"],
        user=env["DB_USER"],
        password=env["DB_PASSWORD"],
        sslrootcert=env.get("DB_SSLROOTCERT") or None,
    )


def connect(settings: DbSettings) -> Any:
    """Open a connection; with sslrootcert, verify the certificate chain and the hostname.

    ssl.create_default_context is used because pg8000's ssl_context=True does not verify
    the server against the RDS CA bundle.
    """
    context = (
        ssl.create_default_context(cafile=settings.sslrootcert) if settings.sslrootcert else None
    )
    return pg8000.native.Connection(
        user=settings.user,
        host=settings.host,
        port=settings.port,
        database=settings.database,
        password=settings.password,
        ssl_context=context,
        timeout=30,
    )


def migrate(conn: Any, files: Sequence[Migration]) -> list[str]:
    """Apply all pending migrations in one transaction; return the versions applied.

    The advisory lock makes concurrent runners (e.g. two terminals on EC2) apply in turn.
    Files run through the simple-query protocol because each holds many statements.
    """
    conn.run("BEGIN")
    try:
        conn.run("SELECT pg_advisory_xact_lock(:key)", key=MIGRATION_LOCK_KEY)
        conn.run(LEDGER_DDL)
        applied = {v: c for v, c in conn.run("SELECT version, checksum FROM schema_migrations")}
        todo = pending_migrations(files, applied)
        for m in todo:
            started = time.monotonic()
            conn.execute_simple(m.sql)
            conn.run(
                "INSERT INTO schema_migrations (version, checksum) VALUES (:v, :c)",
                v=m.version,
                c=m.checksum,
            )
            log_event(
                "migration_applied",
                version=m.version,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
        conn.run("COMMIT")
    except BaseException:
        conn.run("ROLLBACK")
        raise
    return [m.version for m in todo]


def seed(conn: Any, sql: str) -> int:
    """Upsert the seed products; return how many rows were inserted or changed.

    The seed file must stay a single statement: its row count is the reported change count.
    """
    conn.run("BEGIN")
    try:
        conn.run(sql)
        changed = int(conn.row_count)
        conn.run("COMMIT")
    except BaseException:
        conn.run("ROLLBACK")
        raise
    return changed


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--seed", action="store_true", help="upsert db/seed_products.sql")
    args = parser.parse_args(argv)
    try:
        settings = settings_from_env(os.environ if env is None else env)
        conn = connect(settings)
    except (MigrationError, InterfaceError, DatabaseError, OSError) as exc:
        log_event("failed", error=str(exc))
        return 1
    try:
        applied = migrate(conn, load_migrations())
        log_event("migrations_done", applied=applied, count=len(applied))
        if args.seed:
            changed = seed(conn, SEED_FILE.read_text(encoding="utf-8"))
            log_event("seed_done", count=changed)
    except (MigrationError, DatabaseError) as exc:
        log_event("failed", error=str(exc))
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
