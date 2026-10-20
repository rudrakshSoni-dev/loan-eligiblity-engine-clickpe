"""split-csv handler against moto S3 + SQS: uploads in, chunk or control messages out."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from lambdas.shared.batches import upload_key
from lambdas.shared.chunks import (
    ChunkMessage,
    SendError,
    SplitFailure,
    parse_message,
    read_chunk,
    send_messages,
)
from lambdas.shared.config import SplitCsvConfig
from lambdas.shared.loading import validate_chunk
from lambdas.shared.validation import REQUIRED_COLUMNS, validate_file
from lambdas.split_csv import handler as module

REGION = "ap-southeast-2"
BUCKET = "clickpe-loan-uploads-test"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
BATCH = uuid.UUID("00000000-0000-4000-8000-0000000000ee")
MAX_BYTES = 200_000


@dataclass(frozen=True)
class Aws:
    app: module.Runtime
    s3: Any
    sqs: Any

    @property
    def config(self) -> SplitCsvConfig:
        return self.app.config


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[Aws]:
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    monkeypatch.setenv("AWS_REGION", REGION)
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
        sqs = boto3.client("sqs", region_name=REGION)
        queue_url = sqs.create_queue(QueueName="ingest")["QueueUrl"]
        app = module.Runtime(SplitCsvConfig(queue_url, MAX_BYTES, 3), s3, sqs)
        monkeypatch.setattr(module, "runtime", lambda: app)
        yield Aws(app, s3, sqs)


def put(aws: Aws, data: bytes, key: str = upload_key(BATCH)) -> dict[str, Any]:
    etag = aws.s3.put_object(Bucket=BUCKET, Key=key, Body=data)["ETag"].strip('"')
    return s3_event(key, etag, len(data))


def s3_event(key: str, etag: str, size: int) -> dict[str, Any]:
    obj = {"key": key.replace("/", "%2F"), "eTag": etag, "size": size}
    return {"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": obj}}]}


def queued(aws: Aws) -> list[ChunkMessage | SplitFailure]:
    messages: list[ChunkMessage | SplitFailure] = []
    while True:
        response = aws.sqs.receive_message(QueueUrl=aws.config.queue_url, MaxNumberOfMessages=10)
        batch = response.get("Messages", [])
        if not batch:
            return sorted(messages, key=lambda m: getattr(m, "chunk_no", -1))
        messages.extend(parse_message(m["Body"]) for m in batch)


def chunk_messages(aws: Aws) -> list[ChunkMessage]:
    messages = queued(aws)
    assert all(isinstance(m, ChunkMessage) for m in messages), messages
    return [m for m in messages if isinstance(m, ChunkMessage)]


def test_upload_becomes_chunks_that_load_chunk_reads_back(aws: Aws) -> None:
    data = (FIXTURES / "malformed_users.csv").read_bytes()
    assert module.handler(put(aws, data), None) == {"messages_sent": 4}

    messages = chunk_messages(aws)
    assert [(m.chunk_no, m.total_chunks, m.row_count) for m in messages] == [
        (0, 4, 3),
        (1, 4, 3),
        (2, 4, 3),
        (3, 4, 2),
    ]
    parts = [validate_chunk(read_chunk(aws.s3, BUCKET, m), m) for m in messages]
    _, whole = validate_file(data.decode())
    assert [v for p in parts for v in p.valid] == whole.valid
    assert [r.line_no for p in parts for r in p.rejects] == [r.line_no for r in whole.rejects]


def test_more_than_ten_chunks_are_sent_in_several_batches(aws: Aws) -> None:
    rows = [
        f"00000000-0000-4000-8000-{n:012d},User {n},u{n}@example.invalid,50000,700,Salaried,30"
        for n in range(1, 41)
    ]
    data = ("\r\n".join([",".join(REQUIRED_COLUMNS), *rows]) + "\r\n").encode()
    assert module.handler(put(aws, data), None) == {"messages_sent": 14}
    messages = chunk_messages(aws)
    assert [m.chunk_no for m in messages] == list(range(14))
    assert sum(m.row_count for m in messages) == 40


@pytest.mark.parametrize(
    ("fixture", "error"),
    [
        ("header_mismatch.csv", "missing columns: age; repeated columns: email"),
        ("header_only.csv", "file has no data rows"),
    ],
)
def test_unusable_file_sends_one_control_message(aws: Aws, fixture: str, error: str) -> None:
    module.handler(put(aws, (FIXTURES / fixture).read_bytes()), None)
    assert queued(aws) == [SplitFailure(batch_id=BATCH, error=error)]


def test_oversize_event_fails_the_batch_without_reading_s3(aws: Aws) -> None:
    module.handler(s3_event(upload_key(BATCH), "never-read", MAX_BYTES + 1), None)
    expected = f"file is {MAX_BYTES + 1} bytes, the limit is {MAX_BYTES}"
    assert queued(aws) == [SplitFailure(batch_id=BATCH, error=expected)]


def test_object_larger_than_its_event_is_still_refused(
    aws: Aws, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = put(aws, (FIXTURES / "good_users.csv").read_bytes())
    small_cap = module.Runtime(SplitCsvConfig(aws.config.queue_url, 100, 3), aws.s3, aws.sqs)
    monkeypatch.setattr(module, "runtime", lambda: small_cap)
    event["Records"][0]["s3"]["object"]["size"] = 50
    module.handler(event, None)
    [message] = queued(aws)
    assert isinstance(message, SplitFailure)
    assert message.error.endswith("the limit is 100")


def test_deleted_object_fails_the_batch(aws: Aws) -> None:
    module.handler(s3_event(upload_key(BATCH), "gone", 10), None)
    assert queued(aws) == [SplitFailure(batch_id=BATCH, error="upload is no longer in S3")]


def test_replaced_object_is_skipped_for_the_newer_event(aws: Aws) -> None:
    first = put(aws, (FIXTURES / "good_users.csv").read_bytes())
    put(aws, (FIXTURES / "malformed_users.csv").read_bytes())
    assert module.handler(first, None) == {"messages_sent": 0}
    assert queued(aws) == []


def test_foreign_key_is_ignored(aws: Aws) -> None:
    event = put(aws, (FIXTURES / "good_users.csv").read_bytes(), key="uploads/manual.csv")
    assert module.handler(event, None) == {"messages_sent": 0}
    assert queued(aws) == []


def test_duplicate_event_sends_identical_chunks(aws: Aws) -> None:
    event = put(aws, (FIXTURES / "bom_crlf_quoted.csv").read_bytes())
    module.handler(event, None)
    first = chunk_messages(aws)
    module.handler(event, None)
    assert chunk_messages(aws) == first


def test_transient_s3_error_propagates_for_the_async_retry(aws: Aws) -> None:
    class BrokenS3:
        def get_object(self, **_kwargs: str) -> dict[str, Any]:
            raise ClientError({"Error": {"Code": "SlowDown"}}, "GetObject")

    app = module.Runtime(aws.config, BrokenS3(), aws.app.sqs)
    with pytest.raises(ClientError):
        module.split_record(app, s3_event(upload_key(BATCH), "e", 10)["Records"][0])


class FlakySqs:
    def __init__(self, refusals: int) -> None:
        self.refusals = refusals
        self.calls: list[list[str]] = []

    def send_message_batch(
        self,
        *,
        QueueUrl: str,  # noqa: N803
        Entries: list[dict[str, str]],  # noqa: N803
    ) -> dict[str, Any]:
        self.calls.append([e["Id"] for e in Entries])
        if self.refusals == 0:
            return {"Successful": [{"Id": e["Id"]} for e in Entries]}
        self.refusals -= 1
        return {"Failed": [{"Id": Entries[0]["Id"], "Code": "InternalError"}]}


def control(n: int) -> SplitFailure:
    return SplitFailure(batch_id=BATCH, error=f"e{n}")


def test_refused_entries_are_resent_once() -> None:
    sqs = FlakySqs(refusals=1)
    assert send_messages(sqs, "https://q", [control(n) for n in range(12)]) == 12
    assert sqs.calls == [[str(n) for n in range(10)], ["0"], ["10", "11"]]


def test_entries_refused_twice_raise() -> None:
    with pytest.raises(SendError, match="SQS refused 1 message"):
        send_messages(FlakySqs(refusals=2), "https://q", [control(1)])


def test_runtime_reads_config_and_pins_the_regional_s3_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_REGION", REGION)
    monkeypatch.setenv("INGEST_QUEUE_URL", "https://sqs.ap-southeast-2.amazonaws.com/1/ingest")
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "20971520")
    monkeypatch.setenv("CHUNK_ROWS", "5000")
    module.runtime.cache_clear()
    try:
        app: Any = module.runtime()
        assert app.config == SplitCsvConfig(
            "https://sqs.ap-southeast-2.amazonaws.com/1/ingest", 20971520, 5000
        )
        assert app.s3.meta.endpoint_url == f"https://s3.{REGION}.amazonaws.com"
        assert app.sqs.meta.region_name == REGION
    finally:
        module.runtime.cache_clear()
