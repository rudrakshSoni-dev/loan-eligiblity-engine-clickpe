"""PostgreSQL access for the VPC Lambdas: one verified-TLS connection reused across invocations.

A warm Lambda keeps its connection, so most invocations skip the TCP + TLS + SCRAM handshake.
Before each use the connection is checked with a cheap query; a connection that died while the
Lambda was frozen is replaced once. pg8000's native API is used, which is in autocommit mode
unless a transaction is opened with `transaction()`.
"""

from __future__ import annotations

import ssl
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from typing import Any

import pg8000.native
from pg8000.exceptions import DatabaseError, InterfaceError

from lambdas.shared.config import DbConfig

CONNECT_TIMEOUT_SECONDS = 10

Connection = Any
Connector = Callable[[DbConfig], Connection]


def tls_context(ca_bundle: str | None) -> ssl.SSLContext | None:
    """Return a context that verifies the certificate chain and hostname, or None for plain.

    pg8000's `ssl_context=True` encrypts with minimal checks, so a verifying context is built.
    """
    if ca_bundle is None:
        return None
    return ssl.create_default_context(cafile=ca_bundle)


def open_connection(config: DbConfig) -> Connection:
    ca_bundle = str(config.ca_bundle) if config.ca_bundle else None
    return pg8000.native.Connection(
        user=config.user,
        host=config.host,
        port=config.port,
        database=config.database,
        password=config.password,
        ssl_context=tls_context(ca_bundle),
        timeout=CONNECT_TIMEOUT_SECONDS,
    )


def server_error(error: DatabaseError) -> tuple[str, str]:
    """Return (SQLSTATE, message) from a pg8000 server error; empty strings if it carries none."""
    details = error.args[0] if error.args and isinstance(error.args[0], dict) else {}
    return str(details.get("C", "")), str(details.get("M", ""))


def is_alive(conn: Connection) -> bool:
    try:
        conn.run("SELECT 1")
    except (InterfaceError, DatabaseError, OSError):
        return False
    return True


class Database:
    """Lazily opened connection that survives warm invocations and reconnects when stale."""

    def __init__(self, config: DbConfig, connector: Connector = open_connection) -> None:
        self._config = config
        self._connector = connector
        self._conn: Connection | None = None

    def connection(self) -> Connection:
        if self._conn is not None and is_alive(self._conn):
            return self._conn
        self.reset()
        self._conn = self._connector(self._config)
        return self._conn

    def reset(self) -> None:
        """Drop the cached connection, e.g. after an error left it in an unknown state."""
        if self._conn is not None:
            with suppress(InterfaceError, OSError):
                self._conn.close()
        self._conn = None


@contextmanager
def transaction(conn: Connection) -> Iterator[Connection]:
    """Run the block in one transaction: COMMIT on success, ROLLBACK on any exception.

    A failed ROLLBACK on a dead connection is ignored so the original error is the one raised;
    the server discards an open transaction when its connection drops.
    """
    conn.run("BEGIN")
    try:
        yield conn
    except BaseException:
        with suppress(InterfaceError, OSError):
            conn.run("ROLLBACK")
        raise
    conn.run("COMMIT")
