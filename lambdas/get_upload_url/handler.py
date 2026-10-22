"""Function URL handler: create a pending batch and return a presigned S3 POST for its CSV.

Runs inside the VPC because it writes the batch row to RDS. Presigning is local signing, so no
AWS API call leaves the VPC. Configuration is read on the first invocation, not at import, so
the module imports cleanly in the packaging check.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import cache
from http import HTTPStatus
from typing import Any

from pg8000.exceptions import DatabaseError, InterfaceError

from lambdas.shared.batches import create_batch
from lambdas.shared.config import UploadUrlConfig, log_level, upload_url_config
from lambdas.shared.db import Database
from lambdas.shared.logging import configure_logging, log_event, timed
from lambdas.shared.uploads import (
    PRESIGN_EXPIRY_SECONDS,
    S3PostSigner,
    new_s3_client,
    presigned_upload,
)

logger = logging.getLogger("get_upload_url")

ALLOWED_METHOD = "POST"


@dataclass(frozen=True)
class Runtime:
    """Objects built once per warm container: config, database, S3 signer."""

    config: UploadUrlConfig
    database: Database
    s3: S3PostSigner


@cache
def runtime() -> Runtime:
    """Configure logging and build the Runtime on the first invocation."""
    configure_logging(log_level(os.environ))
    config = upload_url_config(os.environ)
    return Runtime(
        config=config,
        database=Database(config.db),
        s3=new_s3_client(os.environ["AWS_REGION"]),
    )


def json_response(status: HTTPStatus, body: dict[str, Any]) -> dict[str, Any]:
    """Build a Function URL JSON response."""
    return {
        "statusCode": status.value,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def http_method(event: dict[str, Any]) -> str:
    """Return the request's HTTP method, upper-cased."""
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    return str(method).upper()


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Create a batch row and return `{batch_id, upload: {url, fields}, ...}` for the browser."""
    app = runtime()
    if http_method(event) != ALLOWED_METHOD:
        log_event(logger, "method_rejected", level=logging.WARNING, method=http_method(event))
        return json_response(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "use POST"})
    try:
        with timed(logger, "upload_url_issued") as fields:
            batch_id = create_batch(app.database.connection())
            fields["batch_id"] = str(batch_id)
            upload = presigned_upload(
                app.s3, app.config.bucket, batch_id, app.config.max_upload_bytes
            )
    except (DatabaseError, InterfaceError, OSError):
        app.database.reset()
        return json_response(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "database unavailable"})
    return json_response(
        HTTPStatus.OK,
        {
            "batch_id": str(batch_id),
            "upload": upload,
            "max_upload_bytes": app.config.max_upload_bytes,
            "expires_in_seconds": PRESIGN_EXPIRY_SECONDS,
        },
    )
