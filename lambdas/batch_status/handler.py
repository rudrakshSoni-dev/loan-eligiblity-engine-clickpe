"""Function URL handler: `GET ?batch_id=<uuid>` returns the batch's progress for the UI poller.

Runs inside the VPC because it reads RDS. Read-only: it never changes a batch. Configuration is
read on the first invocation, not at import, so the module imports cleanly in the packaging check.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from functools import cache
from http import HTTPStatus
from typing import Any

from pg8000.exceptions import DatabaseError, InterfaceError

from lambdas.shared.config import BatchStatusConfig, batch_status_config, log_level
from lambdas.shared.db import Database
from lambdas.shared.logging import configure_logging, log_event, timed
from lambdas.shared.status import batch_status

logger = logging.getLogger("batch_status")

ALLOWED_METHOD = "GET"


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


def http_method(event: dict[str, Any]) -> str:
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    return str(method).upper()


def requested_batch_id(event: dict[str, Any]) -> uuid.UUID | None:
    raw = (event.get("queryStringParameters") or {}).get("batch_id", "")
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Return the progress document for `batch_id`, or 400 / 404 / 405 / 503."""
    app = runtime()
    if http_method(event) != ALLOWED_METHOD:
        log_event(logger, "method_rejected", level=logging.WARNING, method=http_method(event))
        return json_response(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "use GET"})
    batch_id = requested_batch_id(event)
    if batch_id is None:
        return json_response(HTTPStatus.BAD_REQUEST, {"error": "batch_id must be a UUID"})
    try:
        with timed(logger, "status_read", batch_id=str(batch_id)) as fields:
            document = batch_status(app.database.connection(), batch_id)
            fields["found"] = document is not None
    except (DatabaseError, InterfaceError, OSError):
        app.database.reset()
        return json_response(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "database unavailable"})
    if document is None:
        return json_response(HTTPStatus.NOT_FOUND, {"error": "unknown batch_id"})
    return json_response(HTTPStatus.OK, document)
