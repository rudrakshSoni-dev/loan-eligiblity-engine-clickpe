"""The presigned POST policy: what S3 will enforce for the upload, decoded from a real signature."""

import base64
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from lambdas.shared.batches import upload_key
from lambdas.shared.uploads import (
    CSV_CONTENT_TYPE,
    MIN_UPLOAD_BYTES,
    PRESIGN_EXPIRY_SECONDS,
    new_s3_client,
    presigned_upload,
)

BATCH = uuid.UUID("00000000-0000-4000-8000-000000000001")
BUCKET = "clickpe-loan-uploads-test"
REGION = "ap-southeast-2"
MAX_BYTES = 20 * 1024 * 1024


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "example-secret")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)


def decoded_policy(fields: dict[str, str]) -> dict[str, Any]:
    policy: dict[str, Any] = json.loads(base64.b64decode(fields["policy"]))
    return policy


def test_policy_pins_bucket_key_content_type_and_size_range() -> None:
    upload = presigned_upload(new_s3_client(REGION), BUCKET, BATCH, MAX_BYTES)
    conditions = decoded_policy(upload["fields"])["conditions"]
    assert {"bucket": BUCKET} in conditions
    assert {"key": upload_key(BATCH)} in conditions
    assert {"Content-Type": CSV_CONTENT_TYPE} in conditions
    assert ["content-length-range", MIN_UPLOAD_BYTES, MAX_BYTES] in conditions


def test_form_fields_carry_the_pinned_key_and_content_type() -> None:
    fields = presigned_upload(new_s3_client(REGION), BUCKET, BATCH, MAX_BYTES)["fields"]
    assert fields["key"] == f"uploads/{BATCH}.csv"
    assert fields["Content-Type"] == CSV_CONTENT_TYPE
    assert fields["x-amz-algorithm"] == "AWS4-HMAC-SHA256"
    assert fields["x-amz-signature"]


def test_policy_expires_in_five_minutes() -> None:
    fields = presigned_upload(new_s3_client(REGION), BUCKET, BATCH, MAX_BYTES)["fields"]
    expiration = datetime.fromisoformat(decoded_policy(fields)["expiration"])
    remaining = (expiration - datetime.now(UTC)).total_seconds()
    assert PRESIGN_EXPIRY_SECONDS - 10 < remaining <= PRESIGN_EXPIRY_SECONDS


def test_url_is_the_regional_bucket_endpoint() -> None:
    upload = presigned_upload(new_s3_client(REGION), BUCKET, BATCH, MAX_BYTES)
    assert upload["url"] == f"https://{BUCKET}.s3.{REGION}.amazonaws.com/"


def test_each_batch_gets_its_own_key() -> None:
    other = uuid.UUID("00000000-0000-4000-8000-000000000002")
    s3 = new_s3_client(REGION)
    first = presigned_upload(s3, BUCKET, BATCH, MAX_BYTES)["fields"]["key"]
    second = presigned_upload(s3, BUCKET, other, MAX_BYTES)["fields"]["key"]
    assert first != second
