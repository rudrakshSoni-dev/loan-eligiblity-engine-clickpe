"""Chunk decoding, the staging CSV, and the SQL each load step sends, with a scripted connection."""

import csv
import uuid
from decimal import Decimal
from typing import Any

from lambdas.shared.batches import upload_key
from lambdas.shared.chunks import ChunkMessage
from lambdas.shared.loading import (
    MAX_STORED_REJECTS_PER_CHUNK,
    REPLACEMENT_CHARACTER,
    UNDECODABLE_REASON,
    decode_chunk,
    has_undecodable,
    staging_csv,
    storable,
    store_rejects,
    upsert_users,
    validate_chunk,
)
from lambdas.shared.validation import REQUIRED_COLUMNS, Reject, UserRow

BATCH = uuid.UUID("00000000-0000-4000-8000-0000000000bb")
ROW = UserRow(
    user_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
    name='Asha "AJ", Rao',
    email="asha@example.invalid",
    monthly_income=Decimal("45000.50"),
    credit_score=720,
    employment_status="Salaried",
    age=31,
)
GOOD_LINE = (
    b"00000000-0000-4000-8000-000000000002,Ravi,ravi@example.invalid,30000,700,Salaried,30\n"
)


class ScriptedConnection:
    def __init__(self, *results: list[list[Any]]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, sql: str, **params: Any) -> list[list[Any]]:
        self.calls.append((sql, params))
        return self.results.pop(0) if self.results else []


def message_for(data: bytes, first_line_no: int = 2) -> ChunkMessage:
    return ChunkMessage(
        batch_id=BATCH,
        s3_key=upload_key(BATCH),
        etag="e",
        chunk_no=0,
        total_chunks=1,
        start_byte=0,
        end_byte=len(data),
        first_line_no=first_line_no,
        row_count=data.count(b"\n"),
        columns=REQUIRED_COLUMNS,
    )


def test_invalid_utf8_rejects_only_its_own_record() -> None:
    bad = (
        b"00000000-0000-4000-8000-000000000003,R\xe9na,rena@example.invalid,30000,700,Salaried,30\n"
    )
    data = GOOD_LINE + bad + GOOD_LINE.replace(b"0002", b"0004")

    result = validate_chunk(data, message_for(data, first_line_no=10))

    assert [row.name for row in result.valid] == ["Ravi", "Ravi"]
    assert [(r.line_no, r.reason) for r in result.rejects] == [(11, UNDECODABLE_REASON)]
    assert has_undecodable(result.rejects[0].raw)
    assert REPLACEMENT_CHARACTER in storable(result.rejects[0].raw)
    assert not has_undecodable(storable(result.rejects[0].raw))


def test_multibyte_utf8_is_kept() -> None:
    data = GOOD_LINE.replace(b"Ravi", "Rávi Śarmā".encode())
    assert validate_chunk(data, message_for(data)).valid[0].name == "Rávi Śarmā"


def test_decode_keeps_bad_bytes_reversible() -> None:
    assert decode_chunk(b"a\xffb").encode("utf-8", errors="surrogateescape") == b"a\xffb"


def test_storable_replaces_nul_and_leaves_clean_text_alone() -> None:
    assert storable("a\x00b") == f"a{REPLACEMENT_CHARACTER}b"
    assert storable("plain, text") == "plain, text"


def test_staging_csv_round_trips_quotes_and_commas() -> None:
    rows = list(csv.reader(staging_csv([ROW, ROW])))
    assert rows[0] == [
        "0",
        str(ROW.user_id),
        'Asha "AJ", Rao',
        "asha@example.invalid",
        "45000.50",
        "720",
        "Salaried",
        "31",
    ]
    assert rows[1][0] == "1"


def test_upsert_with_no_rows_sends_no_sql() -> None:
    conn = ScriptedConnection()
    counts = upsert_users(conn, BATCH, [])
    assert (counts.inserted, counts.updated, counts.unchanged) == (0, 0, 0)
    assert conn.calls == []


def test_upsert_creates_staging_copies_and_counts_inserted_updated_unchanged() -> None:
    conn = ScriptedConnection([], [], [[True], [False]])
    counts = upsert_users(conn, BATCH, [ROW, ROW, ROW])

    create, copy, upsert = conn.calls
    assert "CREATE TEMP TABLE chunk_staging" in create[0]
    assert "ON COMMIT DROP" in create[0]
    assert copy[0].startswith("COPY chunk_staging (seq, user_id,")
    assert copy[1]["stream"].getvalue().count("\n") == 3
    assert "DISTINCT ON (user_id)" in upsert[0]
    assert "ORDER BY user_id, seq" in upsert[0]
    assert "IS DISTINCT FROM" in upsert[0]
    assert "u.batch_id" not in upsert[0]
    assert upsert[1] == {"batch_id": BATCH}
    assert (counts.inserted, counts.updated, counts.unchanged) == (1, 1, 1)


def test_no_rejects_sends_no_sql() -> None:
    conn = ScriptedConnection()
    assert store_rejects(conn, BATCH, []) == 0
    assert conn.calls == []


def test_rejects_are_capped_per_chunk_and_made_storable() -> None:
    rejects = [Reject(line_no=n, reason="age: missing", raw="x\x00y") for n in range(2, 300)]
    conn = ScriptedConnection()

    stored = store_rejects(conn, BATCH, rejects)

    params = conn.calls[0][1]
    assert stored == MAX_STORED_REJECTS_PER_CHUNK
    assert params["lines"] == list(range(2, 2 + MAX_STORED_REJECTS_PER_CHUNK))
    assert params["raws"][0] == f"x{REPLACEMENT_CHARACTER}y"
    assert params["batch_id"] == BATCH
