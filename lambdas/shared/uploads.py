"""Presigned S3 POST for CSV uploads: the browser sends the file straight to S3, not through Lambda.

Only POST policies let S3 itself enforce a size range, so the 20 MB cap, the exact object key and
the `text/csv` content type are conditions signed into the policy. Anything that breaks one is
rejected by S3 before a byte is stored. `split-csv` re-checks the stored size as a second guard.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol, TypedDict

from lambdas.shared.batches import upload_key

CSV_CONTENT_TYPE = "text/csv"
MIN_UPLOAD_BYTES = 1
PRESIGN_EXPIRY_SECONDS = 300


class PresignedUpload(TypedDict):
    """The URL and form fields the browser posts the CSV with."""

    url: str
    fields: dict[str, str]


class S3PostSigner(Protocol):
    """The part of the boto3 S3 client that signs a presigned POST."""

    def generate_presigned_post(
        self,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        Fields: dict[str, str],  # noqa: N803
        Conditions: list[Any],  # noqa: N803
        ExpiresIn: int,  # noqa: N803
    ) -> dict[str, Any]: ...


def new_s3_client(region: str) -> S3PostSigner:
    """Build a SigV4 client for `region`; boto3 is imported here so importing this module is cheap.

    boto3 builds presigned POST URLs on the global `s3.amazonaws.com` host unless an endpoint is
    given. For a bucket outside us-east-1 that host answers a POST with a redirect, which a
    browser cannot follow from a cross-origin form post, so the regional endpoint is pinned.
    """
    import boto3
    from botocore.config import Config

    client: S3PostSigner = boto3.client(
        "s3",
        region_name=region,
        endpoint_url=f"https://s3.{region}.amazonaws.com",
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )
    return client


def presigned_upload(
    s3: S3PostSigner, bucket: str, batch_id: uuid.UUID, max_upload_bytes: int
) -> PresignedUpload:
    """Return the URL and form fields for uploading `uploads/{batch_id}.csv` within the limits."""
    post = s3.generate_presigned_post(
        Bucket=bucket,
        Key=upload_key(batch_id),
        Fields={"Content-Type": CSV_CONTENT_TYPE},
        Conditions=[
            {"Content-Type": CSV_CONTENT_TYPE},
            ["content-length-range", MIN_UPLOAD_BYTES, max_upload_bytes],
        ],
        ExpiresIn=PRESIGN_EXPIRY_SECONDS,
    )
    return PresignedUpload(url=post["url"], fields=dict(post["fields"]))
