"""Chunk message contract (encode, parse, refusals) and the ranged S3 read's error mapping."""

import io
import json
import uuid
from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from lambdas.shared.batches import upload_key
from lambdas.shared.chunks import (
    ChunkMessage,
    ChunkRejectedError,
    ChunkUnavailableError,
    MessageError,
    SplitFailure,
    encode_message,
    new_s3_reader,
    parse_message,
    read_chunk,
)
from tests.chunk_helpers import BUCKET, FakeS3, line_chunks

BATCH = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
MESSAGE = ChunkMessage(
    batch_id=BATCH,
    s3_key=upload_key(BATCH),
    etag="0123abcd",
    chunk_no=1,
    total_chunks=3,
    start_byte=70,
    end_byte=170,
    first_line_no=5002,
    row_count=5000,
    columns=("user_id", "name", "email", "monthly_income", "credit_score", "employment_status"),
)


def body(**changes: Any) -> str:
    data = json.loads(encode_message(MESSAGE))
    data.update(changes)
    return json.dumps(data)


def test_chunk_message_round_trips() -> None:
    assert parse_message(encode_message(MESSAGE)) == MESSAGE


def test_split_failure_round_trips() -> None:
    failure = SplitFailure(batch_id=BATCH, error="missing columns: age")
    assert parse_message(encode_message(failure)) == failure


def test_byte_range_is_inclusive_and_size_is_exclusive_end_minus_start() -> None:
    assert MESSAGE.byte_range == "bytes=70-169"
    assert MESSAGE.size == 100


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        ("not json", "body is not JSON"),
        ("[1, 2]", "not a JSON object"),
        (json.dumps({"error": "x"}), "batch_id is missing"),
        (json.dumps({"batch_id": "nope", "error": "x"}), "batch_id is missing or not a UUID"),
        (json.dumps({"batch_id": str(BATCH), "error": ""}), "error must be a non-empty string"),
        (body(etag=None), "etag must be a non-empty string"),
        (body(chunk_no=-1), "chunk_no must be a non-negative integer"),
        (body(start_byte="70"), "start_byte must be a non-negative integer"),
        (body(row_count=True), "row_count must be a non-negative integer"),
        (body(columns=[]), "columns must be a non-empty list"),
        (body(columns=["user_id", 3]), "columns must be a non-empty list of strings"),
        (body(s3_key="uploads/other.csv"), "does not belong to batch"),
        (body(chunk_no=3), "chunk_no 3 is not below total_chunks"),
        (body(end_byte=70), "end_byte must be greater than start_byte"),
        (body(first_line_no=0), "first_line_no must be at least 1"),
    ],
)
def test_invalid_messages_are_refused_with_the_reason(raw: str, error: str) -> None:
    with pytest.raises(MessageError, match=error):
        parse_message(raw)


def test_read_chunk_returns_exactly_the_records_of_the_range() -> None:
    data = b"user_id,name\nA,1\nB,2\nC,3\n"
    s3 = FakeS3()
    etag = s3.put(upload_key(BATCH), data)
    message = line_chunks(data, BATCH, etag, rows_per_chunk=2)[1]

    assert read_chunk(s3, BUCKET, message) == b"C,3\n"
    assert s3.reads == [
        {"Bucket": BUCKET, "Key": upload_key(BATCH), "Range": "bytes=21-24", "IfMatch": etag}
    ]


class ScriptedS3:
    def __init__(self, outcome: bytes | Exception) -> None:
        self.outcome = outcome

    def get_object(self, **_kwargs: str) -> dict[str, Any]:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return {"Body": io.BytesIO(self.outcome)}


def client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code}}, "GetObject")


@pytest.mark.parametrize("code", ["PreconditionFailed", "NoSuchKey", "InvalidRange"])
def test_permanent_s3_refusals_reject_the_chunk(code: str) -> None:
    with pytest.raises(ChunkRejectedError, match=code):
        read_chunk(ScriptedS3(client_error(code)), BUCKET, MESSAGE)


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (client_error("SlowDown"), "S3 error SlowDown"),
        (ClientError({}, "GetObject"), "S3 error unknown"),
        (EndpointConnectionError(endpoint_url="https://s3"), "S3 unreachable"),
    ],
)
def test_transient_s3_errors_make_the_chunk_unavailable(error: Exception, text: str) -> None:
    with pytest.raises(ChunkUnavailableError, match=text):
        read_chunk(ScriptedS3(error), BUCKET, MESSAGE)


def test_a_short_read_rejects_the_chunk() -> None:
    with pytest.raises(ChunkRejectedError, match="is 99 bytes, message says 100"):
        read_chunk(ScriptedS3(b"x" * 99), BUCKET, MESSAGE)


def test_s3_reader_uses_the_regional_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "example-secret")
    client: Any = new_s3_reader("ap-southeast-2")
    assert client.meta.endpoint_url == "https://s3.ap-southeast-2.amazonaws.com"
