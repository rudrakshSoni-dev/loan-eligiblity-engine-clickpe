"""Plan the chunk messages for one uploaded CSV: exact byte ranges that hold whole records.

Record boundaries come from the same parser load-chunk uses: `csv.reader` (strict) over the
universal-newline lines of the text, the way `validation.read_records` reads a chunk. The bytes of
the lines each record consumed are summed, so a cut can only fall where load-chunk's own parse of
the whole file would also end a record, and physical line numbers agree in both. The obvious
alternative, a byte scanner that flips "inside quotes" on every `"`, cuts inside records such as
`ab"c,"x<newline>y"`, where the first quote is a literal character.

The text is decoded with `surrogateescape`, so encoding a line back yields its exact bytes even
when the file is not valid UTF-8. A newline byte is never part of a multi-byte character, so a
chunk decodes to exactly the lines it held in the whole file.

Chunks hold `chunk_rows` records each; blank lines ride along with the chunk before them, and a new
chunk starts only at a record, so no chunk is empty. Planning is deterministic: the same bytes
always give the same messages, which is what makes a duplicate S3 event harmless.

`fetch_upload` reads the object with `IfMatch` set to the event's ETag, so the split always reads
the upload the event announced: if the key was uploaded again, the newer object has its own event
and this one is skipped instead of splitting bytes the chunk messages would not describe.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import unquote_plus

from lambdas.shared.batches import UPLOAD_PREFIX, upload_key
from lambdas.shared.chunks import ChunkMessage, SplitFailure
from lambdas.shared.loading import decode_chunk, has_undecodable
from lambdas.shared.validation import BYTE_ORDER_MARK, HeaderError, check_header

UPLOAD_SUFFIX = ".csv"
FILE_ENCODING = "utf-8"
BYTE_ERRORS = "surrogateescape"


class UploadReplacedError(Exception):
    """The object no longer has the event's ETag; a newer upload has its own event."""


class UploadMissingError(Exception):
    """The object is gone, so the batch can never load."""


class S3ObjectReader(Protocol):
    """The part of the boto3 S3 client that reads a whole object version."""

    def get_object(
        self,
        *,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        IfMatch: str,  # noqa: N803
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class Upload:
    """One uploaded CSV as announced by its S3 event."""

    bucket: str
    batch_id: uuid.UUID
    s3_key: str
    etag: str
    size: int


@dataclass(frozen=True, slots=True)
class Span:
    """One CSV record in the file: byte range, line numbers and parsed fields."""

    start: int
    end: int
    first_line_no: int
    next_line_no: int
    is_record: bool
    fields: list[str]


@dataclass(slots=True)
class OpenChunk:
    """A chunk being built: byte range, first line and records so far."""

    start: int
    end: int
    first_line_no: int
    rows: int = 0


def batch_id_from_key(key: str) -> uuid.UUID | None:
    """The batch a key belongs to, or None unless the key is exactly `upload_key(batch_id)`.

    load-chunk refuses a message whose key is not the canonical one, so an upper-case or braced
    UUID is treated as a foreign key here rather than producing chunks that can never load.
    """
    try:
        batch_id = uuid.UUID(key.removeprefix(UPLOAD_PREFIX).removesuffix(UPLOAD_SUFFIX))
    except ValueError:
        return None
    return batch_id if upload_key(batch_id) == key else None


def upload_from_record(record: Mapping[str, Any]) -> Upload | None:
    """The upload an S3 event record announces, or None if it is not a batch upload."""
    s3 = record.get("s3", {})
    obj = s3.get("object", {})
    key = unquote_plus(str(obj.get("key", "")))
    batch_id = batch_id_from_key(key)
    etag = str(obj.get("eTag", ""))
    if batch_id is None or not etag:
        return None
    return Upload(
        bucket=str(s3.get("bucket", {}).get("name", "")),
        batch_id=batch_id,
        s3_key=key,
        etag=etag,
        size=int(obj.get("size", 0)),
    )


def new_s3_object_reader(region: str) -> S3ObjectReader:
    """Build an S3 client on the regional endpoint, like load-chunk's reader."""
    import boto3

    client: S3ObjectReader = boto3.client(
        "s3", region_name=region, endpoint_url=f"https://s3.{region}.amazonaws.com"
    )
    return client


def fetch_upload(s3: S3ObjectReader, upload: Upload) -> bytes:
    """The object's bytes; raise UploadReplacedError / UploadMissingError, or the S3 error."""
    from botocore.exceptions import ClientError

    try:
        response = s3.get_object(Bucket=upload.bucket, Key=upload.s3_key, IfMatch=upload.etag)
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code == "PreconditionFailed":
            raise UploadReplacedError(upload.s3_key) from error
        if code == "NoSuchKey":
            raise UploadMissingError(upload.s3_key) from error
        raise
    data: bytes = response["Body"].read()
    return data


def size_problem(size: int, max_bytes: int) -> str | None:
    """Return why a file of `size` bytes cannot load, or None if the size is fine."""
    if size == 0:
        return "file is empty"
    if size > max_bytes:
        return f"file is {size} bytes, the limit is {max_bytes}"
    return None


def scan_spans(text: str) -> Iterator[Span]:
    """Yield every record (blank and malformed ones too) with its byte range and first line."""
    consumed: list[str] = []

    def tapped_lines() -> Iterator[str]:
        for line in io.StringIO(text, newline=""):
            consumed.append(line)
            yield line

    reader = csv.reader(tapped_lines(), strict=True)
    offset, line_no = 0, 1
    while True:
        malformed = False
        try:
            fields = next(reader)
        except StopIteration:
            return
        except csv.Error:
            fields, malformed = [], True
        size = sum(len(line.encode(FILE_ENCODING, BYTE_ERRORS)) for line in consumed)
        next_line_no = line_no + len(consumed)
        yield Span(offset, offset + size, line_no, next_line_no, bool(fields) or malformed, fields)
        offset, line_no = offset + size, next_line_no
        consumed.clear()


def read_header(spans: Iterator[Span]) -> Span:
    """Consume spans up to and including the header record; raise HeaderError if it is unusable."""
    for span in spans:
        if not span.is_record:
            continue
        if not span.fields:
            raise HeaderError("header row is not valid CSV")
        if any(has_undecodable(name) for name in span.fields):
            raise HeaderError("header row is not valid UTF-8")
        check_header(span.fields)
        return span
    raise HeaderError("file has no header row")


def group_chunks(header: Span, spans: Iterator[Span], chunk_rows: int) -> list[OpenChunk]:
    """Group the records after the header into chunks of `chunk_rows`; no chunk is empty."""
    chunks: list[OpenChunk] = []
    current = OpenChunk(start=header.end, end=header.end, first_line_no=header.next_line_no)
    for span in spans:
        if span.is_record and current.rows == chunk_rows:
            chunks.append(current)
            current = OpenChunk(start=span.start, end=span.start, first_line_no=span.first_line_no)
        current.end = span.end
        current.rows += span.is_record
    if current.rows:
        chunks.append(current)
    return chunks


def plan_chunks(data: bytes, upload: Upload, chunk_rows: int) -> list[ChunkMessage] | SplitFailure:
    """Chunk messages covering every byte after the header, or the reason the file cannot load."""
    spans = scan_spans(decode_chunk(data))
    try:
        header = read_header(spans)
    except HeaderError as error:
        return SplitFailure(batch_id=upload.batch_id, error=str(error))
    chunks = group_chunks(header, spans, chunk_rows)
    if not chunks:
        return SplitFailure(batch_id=upload.batch_id, error="file has no data rows")
    columns = (header.fields[0].removeprefix(BYTE_ORDER_MARK), *header.fields[1:])
    return [
        ChunkMessage(
            batch_id=upload.batch_id,
            s3_key=upload.s3_key,
            etag=upload.etag,
            chunk_no=chunk_no,
            total_chunks=len(chunks),
            start_byte=chunk.start,
            end_byte=chunk.end,
            first_line_no=chunk.first_line_no,
            row_count=chunk.rows,
            columns=columns,
        )
        for chunk_no, chunk in enumerate(chunks)
    ]
