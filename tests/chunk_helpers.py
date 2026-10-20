"""Test doubles for load-chunk: an in-memory S3 that serves byte ranges, and line-based chunking.

`line_chunks` splits on physical lines, so it is only correct for files without quoted newlines.
The real quote-aware splitter is split-csv's job; these helpers only produce valid messages for it.
"""

import csv
import hashlib
import io
import uuid
from typing import Any

from botocore.exceptions import ClientError

from lambdas.shared.batches import upload_key
from lambdas.shared.chunks import ChunkMessage

BUCKET = "clickpe-loan-uploads-test"
FIRST_DATA_LINE = 2


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.reads: list[dict[str, str]] = []

    def put(self, key: str, data: bytes) -> str:
        etag = hashlib.md5(data, usedforsecurity=False).hexdigest()
        self.objects[key] = (data, etag)
        return etag

    def get_object(
        self,
        *,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        Range: str,  # noqa: N803
        IfMatch: str,  # noqa: N803
    ) -> dict[str, Any]:
        self.reads.append({"Bucket": Bucket, "Key": Key, "Range": Range, "IfMatch": IfMatch})
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        data, etag = self.objects[Key]
        if IfMatch.strip('"') != etag:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "GetObject")
        first, last = (int(n) for n in Range.removeprefix("bytes=").split("-"))
        return {"Body": io.BytesIO(data[first : last + 1])}


def line_chunks(
    data: bytes, batch_id: uuid.UUID, etag: str, rows_per_chunk: int
) -> list[ChunkMessage]:
    """Chunk messages covering every data line of `data`, `rows_per_chunk` lines each."""
    header, *lines = data.splitlines(keepends=True)
    columns = tuple(next(csv.reader([header.decode("utf-8-sig")])))
    groups = [lines[i : i + rows_per_chunk] for i in range(0, len(lines), rows_per_chunk)]
    messages = []
    offset, line_no = len(header), FIRST_DATA_LINE
    for chunk_no, group in enumerate(groups):
        size = sum(len(line) for line in group)
        messages.append(
            ChunkMessage(
                batch_id=batch_id,
                s3_key=upload_key(batch_id),
                etag=etag,
                chunk_no=chunk_no,
                total_chunks=len(groups),
                start_byte=offset,
                end_byte=offset + size,
                first_line_no=line_no,
                row_count=len(group),
                columns=columns,
            )
        )
        offset, line_no = offset + size, line_no + len(group)
    return messages
