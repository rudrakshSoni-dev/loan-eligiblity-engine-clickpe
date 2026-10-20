"""Connection reuse, reconnect on a dead connection, transaction commit/rollback, TLS context."""

import ssl
from typing import Any

import pytest
from pg8000.exceptions import DatabaseError, InterfaceError

from lambdas.shared.config import RDS_CA_BUNDLE, DbConfig
from lambdas.shared.db import Database, is_alive, server_error, tls_context, transaction

CONFIG = DbConfig("h", 5432, "d", "u", "p", ca_bundle=None)


class FakeConnection:
    def __init__(self, fail_on: str | None = None) -> None:
        self.statements: list[str] = []
        self.closed = False
        self.fail_on = fail_on

    def run(self, sql: str, **params: Any) -> list[list[Any]]:
        self.statements.append(sql)
        if self.fail_on and sql.startswith(self.fail_on):
            raise InterfaceError("network error")
        return [[1]]

    def close(self) -> None:
        self.closed = True


class Connector:
    def __init__(self) -> None:
        self.opened: list[FakeConnection] = []

    def __call__(self, config: DbConfig) -> FakeConnection:
        conn = FakeConnection()
        self.opened.append(conn)
        return conn


def test_warm_invocations_reuse_one_connection() -> None:
    connector = Connector()
    database = Database(CONFIG, connector)
    assert database.connection() is database.connection()
    assert len(connector.opened) == 1


def test_dead_connection_is_closed_and_replaced() -> None:
    connector = Connector()
    database = Database(CONFIG, connector)
    first = database.connection()
    first.fail_on = "SELECT 1"
    second = database.connection()
    assert second is not first
    assert first.closed
    assert len(connector.opened) == 2


def test_reset_survives_a_connection_that_fails_to_close() -> None:
    class Unclosable(FakeConnection):
        def close(self) -> None:
            raise InterfaceError("already gone")

    database = Database(CONFIG, lambda _config: Unclosable())
    database.connection()
    database.reset()
    database.reset()


def test_is_alive_reports_a_broken_connection() -> None:
    assert is_alive(FakeConnection())
    assert not is_alive(FakeConnection(fail_on="SELECT 1"))


def test_transaction_commits_on_success() -> None:
    conn = FakeConnection()
    with transaction(conn):
        conn.run("INSERT 1")
    assert conn.statements == ["BEGIN", "INSERT 1", "COMMIT"]


def test_transaction_rolls_back_and_reraises() -> None:
    conn = FakeConnection()
    with pytest.raises(RuntimeError, match="boom"), transaction(conn):
        raise RuntimeError("boom")
    assert conn.statements == ["BEGIN", "ROLLBACK"]


def test_failed_rollback_does_not_hide_the_original_error() -> None:
    conn = FakeConnection(fail_on="ROLLBACK")
    with pytest.raises(RuntimeError, match="boom"), transaction(conn):
        raise RuntimeError("boom")


def test_tls_context_verifies_chain_and_hostname_with_the_rds_bundle() -> None:
    context = tls_context(str(RDS_CA_BUNDLE))
    assert context is not None
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    assert len(context.get_ca_certs()) > 100
    assert tls_context(None) is None


def test_server_error_reads_sqlstate_and_message() -> None:
    error = DatabaseError({"S": "ERROR", "C": "23514", "M": "violates check constraint"})
    assert server_error(error) == ("23514", "violates check constraint")


def test_server_error_without_details_is_empty() -> None:
    assert server_error(DatabaseError("plain text")) == ("", "")
