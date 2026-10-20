"""Chunk planning: byte ranges reassemble the file and agree with load-chunk's own parse."""

import itertools
import random
import uuid
from pathlib import Path

import pytest

from lambdas.shared.batches import upload_key
from lambdas.shared.chunks import ChunkMessage, SplitFailure, encode_message, parse_message
from lambdas.shared.loading import validate_chunk
from lambdas.shared.splitting import (
    Upload,
    batch_id_from_key,
    plan_chunks,
    size_problem,
    upload_from_record,
)
from lambdas.shared.validation import REQUIRED_COLUMNS, validate_file

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
BATCH = uuid.UUID("00000000-0000-4000-8000-0000000000dd")
HEADER = ",".join(REQUIRED_COLUMNS)


def upload_of(data: bytes) -> Upload:
    return Upload(
        bucket="b", batch_id=BATCH, s3_key=upload_key(BATCH), etag="etag-1", size=len(data)
    )


def plan(data: bytes, chunk_rows: int) -> list[ChunkMessage]:
    result = plan_chunks(data, upload_of(data), chunk_rows)
    assert isinstance(result, list), result
    return result


def failure(data: bytes) -> str:
    result = plan_chunks(data, upload_of(data), 5)
    assert isinstance(result, SplitFailure), result
    assert result.batch_id == BATCH
    return result.error


def row(n: int, name: str = "Test User") -> str:
    return f"00000000-0000-4000-8000-{n:012d},{name},u{n}@example.invalid,50000,700,Salaried,30"


def assert_matches_whole_file(data: bytes, messages: list[ChunkMessage]) -> None:
    """Chunks tile the file after the header, and per-chunk validation equals whole-file."""
    assert [m.chunk_no for m in messages] == list(range(len(messages)))
    assert {m.total_chunks for m in messages} == {len(messages)}
    for previous, current in itertools.pairwise(messages):
        assert previous.end_byte == current.start_byte
    assert messages[-1].end_byte == len(data)
    header_part = data[: messages[0].start_byte]
    assert header_part + b"".join(data[m.start_byte : m.end_byte] for m in messages) == data
    [single] = plan(data, len(data))
    whole = validate_chunk(data[single.start_byte :], single)
    parts = [validate_chunk(data[m.start_byte : m.end_byte], m) for m in messages]
    assert [v for p in parts for v in p.valid] == whole.valid
    assert [(r.line_no, r.reason) for p in parts for r in p.rejects] == [
        (r.line_no, r.reason) for r in whole.rejects
    ]
    for message, part in zip(messages, parts, strict=True):
        assert len(part.valid) + len(part.rejects) == message.row_count
        assert parse_message(encode_message(message)) == message


@pytest.mark.parametrize(
    ("fixture", "chunk_rows"),
    [
        ("good_users.csv", 2),
        ("good_users.csv", 5),
        ("bom_crlf_quoted.csv", 1),
        ("bom_crlf_quoted.csv", 2),
        ("malformed_users.csv", 3),
        ("malformed_users.csv", 1000),
        ("duplicate_ids.csv", 10),
    ],
)
def test_fixture_chunks_match_whole_file_validation(fixture: str, chunk_rows: int) -> None:
    data = (FIXTURES / fixture).read_bytes()
    assert_matches_whole_file(data, plan(data, chunk_rows))


def test_exact_multiple_of_chunk_size_gives_full_chunks() -> None:
    data = (FIXTURES / "good_users.csv").read_bytes()
    assert [m.row_count for m in plan(data, 5)] == [5]
    assert [m.row_count for m in plan(data, 1)] == [1, 1, 1, 1, 1]
    assert [m.row_count for m in plan(data, 2)] == [2, 2, 1]


def test_quoted_newline_and_crlf_record_stays_whole_and_keeps_line_numbers() -> None:
    data = (FIXTURES / "bom_crlf_quoted.csv").read_bytes()
    messages = plan(data, 1)
    assert [m.first_line_no for m in messages] == [2, 3, 6]
    assert data[messages[1].start_byte : messages[1].end_byte].count(b"\r\n") == 3
    assert messages[0].columns[0] == " AGE "


def test_blank_lines_ride_with_the_chunk_before_them() -> None:
    text = f"{HEADER}\n\n{row(1)}\n{row(2)}\n\n\n{row(3)}\n\n\n"
    data = text.encode()
    messages = plan(data, 2)
    assert [(m.first_line_no, m.row_count) for m in messages] == [(2, 2), (7, 1)]
    assert data[messages[0].start_byte : messages[0].end_byte].startswith(b"\n")
    assert data[messages[1].start_byte :] == f"{row(3)}\n\n\n".encode()
    assert_matches_whole_file(data, messages)


def test_leading_blank_lines_and_multi_line_header_shift_first_line() -> None:
    columns = list(REQUIRED_COLUMNS)
    columns[1] = '"name"'
    text = "\r\n\r\n" + ",".join(columns) + "\r\n" + row(1) + "\r\n"
    multi_line = f'\n{HEADER},"note\nmore"\n{row(1)},x\n{row(2)},y'.encode()
    assert plan(text.encode(), 5)[0].first_line_no == 4
    messages = plan(multi_line, 1)
    assert [m.first_line_no for m in messages] == [4, 5]
    assert messages[0].columns[-1] == "note\nmore"
    assert_matches_whole_file(multi_line, messages)


def test_literal_quote_inside_unquoted_field_is_not_a_cut_point() -> None:
    literal_then_quoted = '00000000-0000-4000-8000-000000000001,ab"c,"u1\n@example.invalid",1,1,x,1'
    data = f"{HEADER}\n{literal_then_quoted}\n{row(2)}\n".encode()
    messages = plan(data, 1)
    assert [(m.first_line_no, m.row_count) for m in messages] == [(2, 1), (4, 1)]
    assert_matches_whole_file(data, messages)


def test_unterminated_quote_becomes_one_malformed_record() -> None:
    unterminated = row(2, name='"open')
    data = f"{HEADER}\n{row(1)}\n{unterminated}\n{row(3)}\n".encode()
    messages = plan(data, 1)
    assert [m.row_count for m in messages] == [1, 1]
    assert_matches_whole_file(data, messages)


def test_invalid_utf8_rejects_only_its_record_at_a_chunk_boundary() -> None:
    data = f"{HEADER}\n{row(1)}\n".encode() + row(2, name="Bad\xff").encode("latin-1") + b"\n"
    data += (row(3, name="Ünïcødé") + "\n").encode()
    messages = plan(data, 1)
    assert len(messages) == 3
    assert_matches_whole_file(data, messages)
    rejects = validate_chunk(data[messages[1].start_byte : messages[1].end_byte], messages[1])
    assert [(r.line_no, r.reason) for r in rejects.rejects] == [(3, "not valid UTF-8")]


def test_random_files_with_quoted_newlines_always_tile_and_agree() -> None:
    generator = random.Random(17)
    lines = [HEADER]
    for n in range(1, 400):
        choice = generator.random()
        if choice < 0.1:
            lines.append(row(n, name=f'"Line\r\nBreak {n}"'))
        elif choice < 0.15:
            lines.append("")
        elif choice < 0.2:
            lines.append(row(n, name=f'"Comma, ""quoted"" {n}"'))
        else:
            lines.append(row(n))
    data = "\r\n".join(lines).encode()
    for chunk_rows in (1, 7, 50, 1000):
        assert_matches_whole_file(data, plan(data, chunk_rows))


def test_one_chunk_agrees_with_whole_file_validation() -> None:
    data = (FIXTURES / "malformed_users.csv").read_bytes()
    [single] = plan(data, len(data))
    _, whole = validate_file(data.decode())
    assert validate_chunk(data[single.start_byte :], single) == whole


def test_planning_is_deterministic() -> None:
    data = (FIXTURES / "bom_crlf_quoted.csv").read_bytes()
    assert plan(data, 1) == plan(data, 1)


@pytest.mark.parametrize(
    ("data", "error"),
    [
        (b"", "file has no header row"),
        (b"\r\n\n", "file has no header row"),
        ((FIXTURES / "header_only.csv").read_bytes(), "file has no data rows"),
        (f"{HEADER}\n\n\n".encode(), "file has no data rows"),
        ((FIXTURES / "header_mismatch.csv").read_bytes(), "missing columns: age"),
        (b'"user_id\n', "header row is not valid CSV"),
        (HEADER.replace("name", "n\xe4me").encode("latin-1") + b"\n", "not valid UTF-8"),
    ],
)
def test_unusable_files_become_one_failure(data: bytes, error: str) -> None:
    assert error in failure(data)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (upload_key(BATCH), BATCH),
        (f"uploads/{str(BATCH).upper()}.csv", None),
        (f"uploads/{{{BATCH}}}.csv", None),
        (f"other/{BATCH}.csv", None),
        (f"uploads/{BATCH}.txt", None),
        ("uploads/not-a-uuid.csv", None),
    ],
)
def test_only_canonical_upload_keys_name_a_batch(key: str, expected: uuid.UUID | None) -> None:
    assert batch_id_from_key(key) == expected


def test_size_problem() -> None:
    assert size_problem(0, 10) == "file is empty"
    assert size_problem(11, 10) == "file is 11 bytes, the limit is 10"
    assert size_problem(10, 10) is None


def s3_record(key: str, etag: str = "abc", size: int = 7) -> dict[str, object]:
    return {"s3": {"bucket": {"name": "bkt"}, "object": {"key": key, "eTag": etag, "size": size}}}


def test_upload_from_record_decodes_the_key() -> None:
    upload = upload_from_record(s3_record(upload_key(BATCH)))
    assert upload == Upload("bkt", BATCH, upload_key(BATCH), "abc", 7)
    encoded = upload_key(BATCH).replace("/", "%2F")
    assert upload_from_record(s3_record(encoded)) == upload


def test_upload_from_record_ignores_foreign_keys_and_missing_etags() -> None:
    assert upload_from_record(s3_record("uploads/x+y.csv")) is None
    assert upload_from_record(s3_record(upload_key(BATCH), etag="")) is None
    assert upload_from_record({}) is None
