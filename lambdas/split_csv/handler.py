"""S3 handler: split an uploaded CSV into chunk messages for load-chunk.

Runs outside the VPC: it reads the object from S3 and sends to SQS over the public endpoints, and
never touches RDS, so the batch's chunk count, its `pending → loading` move and any file-level error
travel in the messages and load-chunk applies them. Per S3 record:
    size check from the event → GetObject (IfMatch = event ETag) → size re-check → plan → send.

An unusable file (empty, over the cap, bad header, no data rows, object deleted) becomes one
`{batch_id, error}` control message, and load-chunk marks the batch failed. A key that is not
`uploads/{uuid}.csv` has no batch to fail and is only logged; so is an object replaced since the
event, because the newer upload has its own event. S3 and SQS errors propagate: Lambda retries the
asynchronous invocation twice, then sends the event to the split-failures queue.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import cache
from typing import Any

from lambdas.shared.chunks import (
    ChunkMessage,
    MessageSender,
    SplitFailure,
    new_sqs_client,
    send_messages,
)
from lambdas.shared.config import SplitCsvConfig, log_level, split_csv_config
from lambdas.shared.logging import configure_logging, log_event, timed
from lambdas.shared.splitting import (
    S3ObjectReader,
    Upload,
    UploadMissingError,
    UploadReplacedError,
    fetch_upload,
    new_s3_object_reader,
    plan_chunks,
    size_problem,
    upload_from_record,
)

logger = logging.getLogger("split_csv")

Plan = list[ChunkMessage | SplitFailure]


@dataclass(frozen=True)
class Runtime:
    """Objects built once per warm container: config, S3 reader, SQS client."""

    config: SplitCsvConfig
    s3: S3ObjectReader
    sqs: MessageSender


@cache
def runtime() -> Runtime:
    """Configure logging and build the Runtime on the first invocation."""
    configure_logging(log_level(os.environ))
    region = os.environ["AWS_REGION"]
    return Runtime(
        config=split_csv_config(os.environ),
        s3=new_s3_object_reader(region),
        sqs=new_sqs_client(region),
    )


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Split every uploaded CSV in the event; return how many messages were queued."""
    app = runtime()
    return {"messages_sent": sum(split_record(app, r) for r in event.get("Records", []))}


def split_record(app: Runtime, record: dict[str, Any]) -> int:
    """Plan and queue the messages for one S3 record; return how many were sent."""
    upload = upload_from_record(record)
    if upload is None:
        key = record.get("s3", {}).get("object", {}).get("key")
        log_event(logger, "upload_ignored", level=logging.WARNING, key=key)
        return 0
    with timed(logger, "upload_split", batch_id=str(upload.batch_id), bytes=upload.size) as fields:
        messages = plan_upload(app, upload)
        chunks = [m for m in messages if isinstance(m, ChunkMessage)]
        fields.update(chunks=len(chunks), count=sum(m.row_count for m in chunks))
        fields.update(errors=[m.error for m in messages if isinstance(m, SplitFailure)])
        return send_messages(app.sqs, app.config.queue_url, messages)


def plan_upload(app: Runtime, upload: Upload) -> Plan:
    """The messages for one upload: its chunks, one control message, or none if it was replaced."""
    problem = size_problem(upload.size, app.config.max_upload_bytes)
    if problem:
        return [SplitFailure(batch_id=upload.batch_id, error=problem)]
    try:
        data = fetch_upload(app.s3, upload)
    except UploadReplacedError:
        log_event(logger, "upload_replaced", batch_id=str(upload.batch_id))
        return []
    except UploadMissingError:
        return [SplitFailure(batch_id=upload.batch_id, error="upload is no longer in S3")]
    problem = size_problem(len(data), app.config.max_upload_bytes)
    if problem:
        return [SplitFailure(batch_id=upload.batch_id, error=problem)]
    plan = plan_chunks(data, upload, app.config.chunk_rows)
    return [plan] if isinstance(plan, SplitFailure) else list(plan)
