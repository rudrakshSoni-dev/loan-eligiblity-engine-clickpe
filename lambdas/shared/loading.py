"""Turn one chunk's bytes into users rows and a reject report, inside the chunk's transaction.

Rows reach `users` through a staging table: COPY is the fastest way into Postgres, and the upsert
from staging lets an existing `user_id` be updated instead of failing the COPY. The upsert:
    * `DISTINCT ON (user_id) … ORDER BY user_id, seq` keeps one row per id (the first in the file),
      because `ON CONFLICT DO UPDATE` refuses a statement that proposes the same key twice, and
      takes row locks in `user_id` order, so two chunks sharing ids cannot deadlock;
    * updates only when a data column differs, so re-uploading an identical file changes 0 rows
      and leaves `batch_id` pointing at the batch that last changed the user.
`RETURNING (xmax = 0)` is the PostgreSQL idiom for telling inserted rows from updated ones.

Bytes are decoded as UTF-8 with `surrogateescape`, so one bad byte rejects only its own record.
Text stored in `rejected_rows` has NUL and undecodable bytes replaced; Postgres text holds neither.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

from lambdas.shared.chunks import ChunkMessage
from lambdas.shared.db import Connection
from lambdas.shared.validation import (
    Record,
    Reject,
    UserRow,
    ValidationResult,
    check_header,
    make_reject,
    read_records,
    validate_rows,
)

MAX_STORED_REJECTS_PER_CHUNK = 100
UNDECODABLE_REASON = "not valid UTF-8"
REPLACEMENT_CHARACTER = "�"
FIRST_ESCAPED_BYTE, LAST_ESCAPED_BYTE = 0xDC80, 0xDCFF
NUL = "\x00"

DATA_COLUMNS = (
    "user_id",
    "name",
    "email",
    "monthly_income",
    "credit_score",
    "employment_status",
    "age",
)

CREATE_STAGING = """
CREATE TEMP TABLE chunk_staging (
    seq               integer       NOT NULL,
    user_id           uuid          NOT NULL,
    name              text          NOT NULL,
    email             text          NOT NULL,
    monthly_income    numeric(12,2) NOT NULL,
    credit_score      smallint      NOT NULL,
    employment_status text          NOT NULL,
    age               smallint      NOT NULL
) ON COMMIT DROP
"""

COPY_STAGING = f"COPY chunk_staging (seq, {', '.join(DATA_COLUMNS)}) FROM STDIN WITH (FORMAT csv)"

UPSERT_USERS = f"""
INSERT INTO users AS u ({", ".join(DATA_COLUMNS)}, batch_id)
SELECT DISTINCT ON (user_id) {", ".join(DATA_COLUMNS)}, CAST(:batch_id AS uuid)
FROM chunk_staging
ORDER BY user_id, seq
ON CONFLICT (user_id) DO UPDATE SET
    {", ".join(f"{c} = EXCLUDED.{c}" for c in DATA_COLUMNS[1:])},
    batch_id = EXCLUDED.batch_id
WHERE ({", ".join(f"u.{c}" for c in DATA_COLUMNS[1:])})
    IS DISTINCT FROM ({", ".join(f"EXCLUDED.{c}" for c in DATA_COLUMNS[1:])})
RETURNING (xmax = 0) AS inserted
"""

INSERT_REJECTS = """
INSERT INTO rejected_rows (batch_id, line_no, reason, raw)
SELECT CAST(:batch_id AS uuid), r.line_no, r.reason, r.raw
FROM unnest(CAST(:lines AS integer[]), CAST(:reasons AS text[]), CAST(:raws AS text[]))
    AS r(line_no, reason, raw)
"""


@dataclass(frozen=True, slots=True)
class UpsertCounts:
    inserted: int
    updated: int
    unchanged: int


def decode_chunk(data: bytes) -> str:
    return data.decode("utf-8", errors="surrogateescape")


def has_undecodable(text: str) -> bool:
    return any(FIRST_ESCAPED_BYTE <= ord(c) <= LAST_ESCAPED_BYTE for c in text)


def storable(text: str) -> str:
    """Replace what a Postgres text column cannot hold: NUL and bytes that were not UTF-8."""
    cleaned = text.replace(NUL, REPLACEMENT_CHARACTER)
    if not has_undecodable(cleaned):
        return cleaned
    return "".join(REPLACEMENT_CHARACTER if has_undecodable(c) else c for c in cleaned)


def reject_undecodable(records: Iterable[Record | Reject]) -> Iterator[Record | Reject]:
    for record in records:
        if isinstance(record, Record) and has_undecodable(record.raw):
            yield make_reject(record.line_no, UNDECODABLE_REASON, record.raw)
        else:
            yield record


def validate_chunk(data: bytes, message: ChunkMessage) -> ValidationResult:
    """Validate the chunk's records against the header layout carried in the message."""
    layout = check_header(message.columns)
    records = read_records(decode_chunk(data), message.first_line_no)
    return validate_rows(reject_undecodable(records), layout)


def staging_csv(rows: Sequence[UserRow]) -> io.StringIO:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for seq, row in enumerate(rows):
        writer.writerow(
            (
                seq,
                row.user_id,
                row.name,
                row.email,
                row.monthly_income,
                row.credit_score,
                row.employment_status,
                row.age,
            )
        )
    buffer.seek(0)
    return buffer


def upsert_users(conn: Connection, batch_id: uuid.UUID, rows: Sequence[UserRow]) -> UpsertCounts:
    """COPY the rows into a transaction-scoped staging table and upsert them into users."""
    if not rows:
        return UpsertCounts(inserted=0, updated=0, unchanged=0)
    conn.run(CREATE_STAGING)
    conn.run(COPY_STAGING, stream=staging_csv(rows))
    changed = conn.run(UPSERT_USERS, batch_id=batch_id)
    inserted = sum(1 for (was_inserted,) in changed if was_inserted)
    return UpsertCounts(
        inserted=inserted,
        updated=len(changed) - inserted,
        unchanged=len(rows) - len(changed),
    )


def store_rejects(conn: Connection, batch_id: uuid.UUID, rejects: Sequence[Reject]) -> int:
    """Store the chunk's first rejects for the report; the full count lives in the ledger."""
    kept = rejects[:MAX_STORED_REJECTS_PER_CHUNK]
    if not kept:
        return 0
    conn.run(
        INSERT_REJECTS,
        batch_id=batch_id,
        lines=[r.line_no for r in kept],
        reasons=[storable(r.reason) for r in kept],
        raws=[storable(r.raw) for r in kept],
    )
    return len(kept)
