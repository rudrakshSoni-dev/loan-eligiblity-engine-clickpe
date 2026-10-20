"""Shared fixture for DB-backed tests: a freshly migrated, throwaway database per test.

Needs a superuser connection to a disposable server:
    TEST_DB_HOST=localhost TEST_DB_PORT=55432 TEST_DB_USER=postgres TEST_DB_PASSWORD=... pytest
"""

import os
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from db.migrate import DbSettings, connect, load_migrations, migrate
from lambdas.shared.config import DbConfig
from lambdas.shared.db import open_connection


def settings(database: str) -> DbSettings:
    return DbSettings(
        host=os.environ["TEST_DB_HOST"],
        port=int(os.environ.get("TEST_DB_PORT", "5432")),
        database=database,
        user=os.environ.get("TEST_DB_USER", "postgres"),
        password=os.environ.get("TEST_DB_PASSWORD", ""),
        sslrootcert=None,
    )


@pytest.fixture
def connect_db() -> Iterator[Callable[[], Any]]:
    """Yield a factory of connections to a fresh, migrated database; close them all at the end."""
    name = f"shared_test_{uuid.uuid4().hex[:12]}"
    admin = connect(settings("postgres"))
    admin.run(f'CREATE DATABASE "{name}"')
    s = settings(name)
    config = DbConfig(s.host, s.port, name, s.user, s.password, ca_bundle=None)
    opened: list[Any] = []

    def factory() -> Any:
        conn = open_connection(config)
        opened.append(conn)
        return conn

    migrate(factory(), load_migrations())
    yield factory
    for conn in opened:
        conn.close()
    admin.run(f'DROP DATABASE "{name}" WITH (FORCE)')
    admin.close()
