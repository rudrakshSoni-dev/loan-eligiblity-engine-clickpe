"""Reject report for the uploader: stored rejects grouped by problem, and a CSV export.

`rejected_rows` keeps the first rejects of every chunk, so both views cover the stored rejects,
not necessarily every rejected row; `upload_batches.rows_rejected` stays the true total.
A reason lists one or more problems joined by "; ", each starting with the column it concerns,
so a row with two bad fields counts once under each of them. The grouping is display-only: a
field value that itself contains "; <column>: " can add one extra problem name for its row.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from collections.abc import Sequence
from typing import Any

from lambdas.shared.db import Connection
from lambdas.shared.validation import REQUIRED_COLUMNS

DOWNLOAD_ROW_LIMIT = 2000
CSV_HEADER = ("line_no", "reason", "raw")
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

REASONS_SQL = "SELECT line_no, reason FROM rejected_rows WHERE batch_id = :id ORDER BY line_no"
DOWNLOAD_SQL = (
    "SELECT line_no, reason, raw FROM rejected_rows WHERE batch_id = :id"
    " ORDER BY line_no LIMIT :limit"
)
BATCH_EXISTS_SQL = "SELECT 1 FROM upload_batches WHERE id = :id"

COLUMN_ALTERNATION = "|".join(REQUIRED_COLUMNS)
PROBLEM_SEPARATOR = re.compile(rf"; (?=(?:{COLUMN_ALTERNATION}): )")
COLUMN_PROBLEM = re.compile(rf"^({COLUMN_ALTERNATION}): ")
DUPLICATE_PREFIX = "user_id: duplicate of line"
FIELD_COUNT = re.compile(r"^expected \d+ fields, got \d+$")
MALFORMED_PREFIX = "malformed CSV"


def problem_of(part: str) -> str:
    """Name the problem one reason part describes: a column, or a whole-row problem."""
    if part.startswith(DUPLICATE_PREFIX):
        return "duplicate user_id"
    column = COLUMN_PROBLEM.match(part)
    if column:
        return column.group(1)
    if FIELD_COUNT.match(part):
        return "wrong number of fields"
    if part.startswith(MALFORMED_PREFIX):
        return "malformed CSV"
    return "other"


def problems_in(reason: str) -> dict[str, str]:
    """Map each problem named in one reason to its first part of the reason text."""
    found: dict[str, str] = {}
    for part in PROBLEM_SEPARATOR.split(reason):
        found.setdefault(problem_of(part), part)
    return found


def summarise(rejects: Sequence[tuple[int, str]]) -> list[dict[str, Any]]:
    """Group (line_no, reason) pairs by problem: row count, first line and its example text."""
    groups: dict[str, dict[str, Any]] = {}
    for line_no, reason in rejects:
        for problem, part in problems_in(reason).items():
            group = groups.setdefault(
                problem, {"problem": problem, "rows": 0, "first_line": line_no, "example": part}
            )
            group["rows"] += 1
    return sorted(groups.values(), key=lambda group: (-group["rows"], group["problem"]))


def stored_reasons(conn: Connection, batch_id: uuid.UUID) -> list[tuple[int, str]]:
    """Return the batch's stored (line_no, reason) pairs in line order."""
    return [(int(line), str(reason)) for line, reason in conn.run(REASONS_SQL, id=batch_id)]


def spreadsheet_safe(value: str | None) -> str:
    """Prefix text a spreadsheet would run as a formula, so opening the file never executes it."""
    text = value or ""
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def rejects_csv(rows: Sequence[tuple[int, str, str | None]]) -> str:
    """Render reject rows as CSV with formula-like cells neutralised."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for line_no, reason, raw in rows:
        writer.writerow((line_no, spreadsheet_safe(reason), spreadsheet_safe(raw)))
    return buffer.getvalue()


def download(conn: Connection, batch_id: uuid.UUID) -> str | None:
    """Return the first `DOWNLOAD_ROW_LIMIT` stored rejects as CSV; None for an unknown batch."""
    if not conn.run(BATCH_EXISTS_SQL, id=batch_id):
        return None
    rows = conn.run(DOWNLOAD_SQL, id=batch_id, limit=DOWNLOAD_ROW_LIMIT)
    return rejects_csv([(int(line), str(reason), raw) for line, reason, raw in rows])
