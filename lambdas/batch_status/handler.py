"""Function URL handler: `GET ?batch_id=<uuid>` returns the batch's progress for the UI poller.

`GET ?batch_id=<uuid>&download=rejects` returns the stored rejected rows as a CSV attachment.
Runs inside the VPC because it reads RDS. Read-only: it never changes a batch. Configuration is
read on the first invocation, not at import, so the module imports cleanly in the packaging check.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from http import HTTPStatus
from typing import Any

from pg8000.exceptions import DatabaseError, InterfaceError

from lambdas.shared.config import BatchStatusConfig, batch_status_config, log_level
from lambdas.shared.db import Connection, Database
from lambdas.shared.logging import configure_logging, log_event, timed
from lambdas.shared.reject_report import download
from lambdas.shared.status import batch_status

logger = logging.getLogger("batch_status")

ALLOWED_METHOD = "GET"
REJECTS_DOWNLOAD = "rejects"


@dataclass(frozen=True)
class Runtime:
    config: BatchStatusConfig
    database: Database


@cache
def runtime() -> Runtime:
    configure_logging(log_level(os.environ))
    config = batch_status_config(os.environ)
    return Runtime(config=config, database=Database(config.db))


def json_response(status: HTTPStatus, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status.value,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(body, default=str),
    }


NOT_FOUND = json_response(HTTPStatus.NOT_FOUND, {"error": "unknown batch_id"})


def csv_attachment(batch_id: uuid.UUID, body: str) -> dict[str, Any]:
    return {
        "statusCode": HTTPStatus.OK.value,
        "headers": {
            "content-type": "text/csv; charset=utf-8",
            "content-disposition": f'attachment; filename="rejected-rows-{batch_id}.csv"',
            "cache-control": "no-store",
        },
        "body": body,
    }


def http_method(event: dict[str, Any]) -> str:
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    return str(method).upper()


def query_parameter(event: dict[str, Any], name: str) -> str | None:
    value = (event.get("queryStringParameters") or {}).get(name)
    return None if value is None else str(value)


def requested_batch_id(event: dict[str, Any]) -> uuid.UUID | None:
    raw = query_parameter(event, "batch_id") or ""
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


class DatabaseUnavailableError(Exception):
    """The read failed on the connection; it has been dropped so the next call reconnects."""


def read_batch[T](
    app: Runtime, stage: str, batch_id: uuid.UUID, reader: Callable[[Connection, uuid.UUID], T]
) -> T:
    try:
        with timed(logger, stage, batch_id=str(batch_id)) as fields:
            result = reader(app.database.connection(), batch_id)
            fields["found"] = result is not None
    except (DatabaseError, InterfaceError, OSError) as error:
        app.database.reset()
        raise DatabaseUnavailableError from error
    return result


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Return the progress document or the rejects CSV for `batch_id`, or 400 / 404 / 405 / 503."""
    app = runtime()
    if http_method(event) != ALLOWED_METHOD:
        log_event(logger, "method_rejected", level=logging.WARNING, method=http_method(event))
        return json_response(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "use GET"})
    batch_id = requested_batch_id(event)
    if batch_id is None:
        return json_response(HTTPStatus.BAD_REQUEST, {"error": "batch_id must be a UUID"})
    wanted = query_parameter(event, "download")
    if wanted not in (None, REJECTS_DOWNLOAD):
        return json_response(HTTPStatus.BAD_REQUEST, {"error": "download must be 'rejects'"})
    try:
        if wanted == REJECTS_DOWNLOAD:
            body = read_batch(app, "rejects_download", batch_id, download)
            return NOT_FOUND if body is None else csv_attachment(batch_id, body)
        document = read_batch(app, "status_read", batch_id, batch_status)
    except DatabaseUnavailableError:
        return json_response(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "database unavailable"})
    return NOT_FOUND if document is None else json_response(HTTPStatus.OK, document)
