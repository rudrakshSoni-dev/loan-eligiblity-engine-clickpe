"""Messages from split-csv to load-chunk, and reading one chunk's exact bytes from S3.

A chunk message names a byte range of `uploads/{batch_id}.csv` that holds whole CSV records, so
load-chunk never sees a partial record. `start_byte` is inclusive and `end_byte` is exclusive, like
a Python slice; the HTTP Range header is inclusive on both ends, so `byte_range` subtracts one.
`etag` is the ETag from the S3 event and is sent as `IfMatch`: if the object was replaced after it
was split, S3 refuses the read instead of returning bytes from a different file.

A split that cannot produce chunks (bad header, oversize file) sends one control message with
`batch_id` and `error` instead, and load-chunk marks the batch failed.

`send_messages` is split-csv's side: SendMessageBatch in groups of 10 (the SQS maximum), with one
resend of the entries SQS reports as failed. Anything still unsent raises, so the S3 invocation is
retried as a whole; chunks already sent arrive twice and the chunk ledger ignores the copies.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from lambdas.shared.batches import upload_key

PERMANENT_S3_ERROR_CODES = frozenset({"NoSuchKey", "PreconditionFailed", "InvalidRange"})
SQS_BATCH_LIMIT = 10
SEND_ATTEMPTS = 2


class MessageError(ValueError):
    """The SQS body is not a valid chunk or control message."""


class ChunkRejectedError(Exception):
    """The chunk can never load as sent (object replaced or gone, wrong length); fail the batch."""


class ChunkUnavailableError(Exception):
    """S3 could not serve the chunk right now; the message should be retried."""


class SendError(Exception):
    """SQS kept refusing some messages; the split must be retried."""


@dataclass(frozen=True, slots=True)
class ChunkMessage:
    """One chunk to load: its batch, object version, byte range and line numbers."""

    batch_id: uuid.UUID
    s3_key: str
    etag: str
    chunk_no: int
    total_chunks: int
    start_byte: int
    end_byte: int
    first_line_no: int
    row_count: int
    columns: tuple[str, ...]

    @property
    def size(self) -> int:
        """Number of bytes in the chunk."""
        return self.end_byte - self.start_byte

    @property
    def byte_range(self) -> str:
        """HTTP Range header value for the chunk (inclusive end)."""
        return f"bytes={self.start_byte}-{self.end_byte - 1}"


@dataclass(frozen=True, slots=True)
class SplitFailure:
    """Control message: the file cannot load, and why."""

    batch_id: uuid.UUID
    error: str


class S3RangeReader(Protocol):
    """The part of the boto3 S3 client that reads one byte range of an object."""

    def get_object(
        self,
        *,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        Range: str,  # noqa: N803
        IfMatch: str,  # noqa: N803
    ) -> dict[str, Any]: ...


class MessageSender(Protocol):
    """The part of the boto3 SQS client that sends a batch of messages."""

    def send_message_batch(
        self,
        *,
        QueueUrl: str,  # noqa: N803
        Entries: list[dict[str, str]],  # noqa: N803
    ) -> dict[str, Any]: ...


def encode_message(message: ChunkMessage | SplitFailure) -> str:
    """Serialise a chunk or control message to the JSON body sent to SQS."""
    if isinstance(message, SplitFailure):
        return json.dumps({"batch_id": str(message.batch_id), "error": message.error})
    return json.dumps(
        {
            "batch_id": str(message.batch_id),
            "s3_key": message.s3_key,
            "etag": message.etag,
            "chunk_no": message.chunk_no,
            "total_chunks": message.total_chunks,
            "start_byte": message.start_byte,
            "end_byte": message.end_byte,
            "first_line_no": message.first_line_no,
            "row_count": message.row_count,
            "columns": list(message.columns),
        }
    )


def parse_message(body: str) -> ChunkMessage | SplitFailure:
    """Decode an SQS body; raise MessageError naming what is wrong."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError as error:
        raise MessageError(f"body is not JSON: {error}") from error
    if not isinstance(data, dict):
        raise MessageError("body is not a JSON object")
    batch_id = batch_id_of(data)
    if "error" in data:
        return SplitFailure(batch_id=batch_id, error=text_field(data, "error"))
    message = ChunkMessage(
        batch_id=batch_id,
        s3_key=text_field(data, "s3_key"),
        etag=text_field(data, "etag"),
        chunk_no=count_field(data, "chunk_no"),
        total_chunks=count_field(data, "total_chunks"),
        start_byte=count_field(data, "start_byte"),
        end_byte=count_field(data, "end_byte"),
        first_line_no=count_field(data, "first_line_no"),
        row_count=count_field(data, "row_count"),
        columns=columns_field(data),
    )
    check_consistency(message)
    return message


def batch_id_of(data: Mapping[str, Any]) -> uuid.UUID:
    """Return the message's batch id; raise MessageError if absent or not a UUID."""
    try:
        return uuid.UUID(str(data["batch_id"]))
    except (KeyError, ValueError) as error:
        raise MessageError("batch_id is missing or not a UUID") from error


def text_field(data: Mapping[str, Any], name: str) -> str:
    """Return a required non-empty string field or raise MessageError."""
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise MessageError(f"{name} must be a non-empty string")
    return value


def count_field(data: Mapping[str, Any], name: str) -> int:
    """Return a required non-negative integer field or raise MessageError."""
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MessageError(f"{name} must be a non-negative integer")
    return value


def columns_field(data: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the header columns as a tuple or raise MessageError."""
    value = data.get("columns")
    if not isinstance(value, list) or not value or not all(isinstance(c, str) for c in value):
        raise MessageError("columns must be a non-empty list of strings")
    return tuple(value)


def check_consistency(message: ChunkMessage) -> None:
    """Raise MessageError if key, chunk number, range or line number disagree."""
    problems = []
    if message.s3_key != upload_key(message.batch_id):
        problems.append(f"s3_key {message.s3_key!r} does not belong to batch {message.batch_id}")
    if message.chunk_no >= message.total_chunks:
        problems.append(f"chunk_no {message.chunk_no} is not below total_chunks")
    if message.end_byte <= message.start_byte:
        problems.append("end_byte must be greater than start_byte")
    if message.first_line_no < 1:
        problems.append("first_line_no must be at least 1")
    if problems:
        raise MessageError("; ".join(problems))


def new_s3_reader(region: str) -> S3RangeReader:
    """Build an S3 client on the regional endpoint, which the VPC's Gateway Endpoint serves."""
    import boto3

    client: S3RangeReader = boto3.client(
        "s3", region_name=region, endpoint_url=f"https://s3.{region}.amazonaws.com"
    )
    return client


def read_chunk(s3: S3RangeReader, bucket: str, message: ChunkMessage) -> bytes:
    """Return exactly the chunk's bytes, or raise ChunkRejectedError / ChunkUnavailableError."""
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        response = s3.get_object(
            Bucket=bucket, Key=message.s3_key, Range=message.byte_range, IfMatch=message.etag
        )
        data: bytes = response["Body"].read()
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code in PERMANENT_S3_ERROR_CODES:
            raise ChunkRejectedError(f"S3 refused chunk {message.chunk_no}: {code}") from error
        raise ChunkUnavailableError(f"S3 error {code or 'unknown'}") from error
    except BotoCoreError as error:
        raise ChunkUnavailableError(f"S3 unreachable: {error}") from error
    if len(data) != message.size:
        raise ChunkRejectedError(
            f"chunk {message.chunk_no} is {len(data)} bytes, message says {message.size}"
        )
    return data


def send_messages(
    sqs: MessageSender, queue_url: str, messages: Sequence[ChunkMessage | SplitFailure]
) -> int:
    """Queue every message; return how many were sent, or raise SendError naming what failed."""
    bodies = [encode_message(message) for message in messages]
    for first in range(0, len(bodies), SQS_BATCH_LIMIT):
        group = bodies[first : first + SQS_BATCH_LIMIT]
        send_group(sqs, queue_url, {str(first + i): body for i, body in enumerate(group)})
    return len(bodies)


def send_group(sqs: MessageSender, queue_url: str, pending: dict[str, str]) -> None:
    """Send up to 10 messages, resending SQS-reported failures once."""
    errors: list[str] = []
    for _ in range(SEND_ATTEMPTS):
        entries = [{"Id": entry_id, "MessageBody": body} for entry_id, body in pending.items()]
        response = sqs.send_message_batch(QueueUrl=queue_url, Entries=entries)
        failed = response.get("Failed", [])
        errors = [f"{f.get('Id')}: {f.get('Code')}" for f in failed]
        pending = {f["Id"]: pending[f["Id"]] for f in failed}
        if not pending:
            return
    raise SendError(f"SQS refused {len(pending)} message(s): {', '.join(errors)}")


def new_sqs_client(region: str) -> MessageSender:
    """Build an SQS client for `region`; boto3 is imported only here."""
    import boto3

    client: MessageSender = boto3.client("sqs", region_name=region)
    return client
