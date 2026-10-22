"""Pure validation of uploaded user CSVs: header check, CSV records, per-row rules, normalisation.

The rules come from the sample profile in docs/data-notes.md and are never looser than the CHECK
constraints on `users` in db/schema.sql. That invariant matters for the loader: one accepted row
that the database refuses would abort the COPY of its whole chunk, so a row either passes here and
in Postgres, or is rejected here with a reason.

Columns are matched by name in any order. A byte-range chunk has no header row, so split-csv sends
`ColumnLayout.columns` with every chunk and load-chunk rebuilds the layout with `check_header`.

Duplicate `user_id`s are detected within the rows given to `validate_rows` (one chunk). Duplicates
in different chunks are not visible here; the loader's upsert keeps one row per `user_id`.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

REQUIRED_COLUMNS = (
    "user_id",
    "name",
    "email",
    "monthly_income",
    "credit_score",
    "employment_status",
    "age",
)
EMPLOYMENT_STATUSES = ("Salaried", "Self-Employed", "Business")
CREDIT_SCORE_MIN, CREDIT_SCORE_MAX = 300, 900
AGE_MIN, AGE_MAX = 18, 100
MAX_NAME_LENGTH = 200
MAX_EMAIL_LENGTH = 254
MAX_RAW_LENGTH = 1000
MAX_SHOWN_VALUE_LENGTH = 40
BYTE_ORDER_MARK = "﻿"
DELETE_CHARACTER = 127
FIRST_PRINTABLE = 32

UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
WHOLE_NUMBER_PATTERN = re.compile(r"[0-9]{1,9}")
AMOUNT_PATTERN = re.compile(r"[0-9]{1,10}(?:\.[0-9]{1,2})?")
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+")
EMPLOYMENT_BY_KEY = {re.sub(r"[^a-z]", "", s.lower()): s for s in EMPLOYMENT_STATUSES}


class HeaderError(ValueError):
    """The header row is missing, unreadable, or lacks or repeats a required column."""


class FieldError(ValueError):
    """One field breaks its rule; the message is shown to the uploader as the reject reason."""


@dataclass(frozen=True, slots=True)
class ColumnLayout:
    """Header columns in file order and the position of each required column."""

    columns: tuple[str, ...]
    positions: Mapping[str, int]

    @property
    def ignored(self) -> tuple[str, ...]:
        """Columns present in the file that the loader does not use."""
        return tuple(c for c in self.columns if c not in REQUIRED_COLUMNS)


@dataclass(frozen=True, slots=True)
class Record:
    """One parsed CSV record with the file line it starts on and its raw text."""

    line_no: int
    fields: list[str]
    raw: str


@dataclass(frozen=True, slots=True)
class Reject:
    """One refused record: its line, every problem found, and its raw text."""

    line_no: int
    reason: str
    raw: str


@dataclass(frozen=True, slots=True)
class UserRow:
    """A validated, normalised row ready for the `users` table."""

    user_id: uuid.UUID
    name: str
    email: str
    monthly_income: Decimal
    credit_score: int
    employment_status: str
    age: int


@dataclass(slots=True)
class ValidationResult:
    """Valid rows and rejects from one chunk or file."""

    valid: list[UserRow] = field(default_factory=list)
    rejects: list[Reject] = field(default_factory=list)


def make_reject(line_no: int, reason: str, raw: str) -> Reject:
    """Build a reject, truncating the raw text to MAX_RAW_LENGTH."""
    return Reject(line_no=line_no, reason=reason, raw=raw[:MAX_RAW_LENGTH])


def shown(value: str) -> str:
    """Quote a value for a reject reason, cut to MAX_SHOWN_VALUE_LENGTH characters."""
    return repr(
        value[:MAX_SHOWN_VALUE_LENGTH] + ("…" if len(value) > MAX_SHOWN_VALUE_LENGTH else "")
    )


def check_header(fields: Sequence[str]) -> ColumnLayout:
    """Map each required column to its position; header names ignore case, spaces and a BOM."""
    names = list(fields)
    if names:
        names[0] = names[0].removeprefix(BYTE_ORDER_MARK)
    columns = tuple(name.strip().lower() for name in names)
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    repeated = [c for c in REQUIRED_COLUMNS if columns.count(c) > 1]
    problems = []
    if missing:
        problems.append(f"missing columns: {', '.join(missing)}")
    if repeated:
        problems.append(f"repeated columns: {', '.join(repeated)}")
    if problems:
        raise HeaderError("; ".join(problems))
    return ColumnLayout(columns=columns, positions={c: columns.index(c) for c in REQUIRED_COLUMNS})


def read_records(text: str, first_line_no: int = 1) -> Iterator[Record | Reject]:
    """Yield each CSV record with the file line it starts on; unparseable records become rejects.

    `line_no` counts physical lines, so a quoted field containing a newline does not shift the
    numbers of later records. Blank lines are skipped but still counted.
    """
    consumed: list[str] = []

    def tapped_lines() -> Iterator[str]:
        for line in io.StringIO(text, newline=""):
            consumed.append(line)
            yield line

    reader = csv.reader(tapped_lines(), strict=True)
    line_no = first_line_no
    while True:
        parse_error = ""
        try:
            fields = next(reader)
        except StopIteration:
            return
        except csv.Error as error:
            fields, parse_error = [], f"malformed CSV: {error}"
        raw = "".join(consumed).rstrip("\r\n")
        consumed.clear()
        if parse_error:
            yield make_reject(line_no, parse_error, raw)
        elif fields:
            yield Record(line_no=line_no, fields=fields, raw=raw)
        line_no = first_line_no + reader.line_num


def parse_user_id(value: str) -> uuid.UUID:
    """Return the UUID or raise FieldError."""
    if not UUID_PATTERN.fullmatch(value):
        raise FieldError(f"{shown(value)} is not a UUID")
    return uuid.UUID(value)


def parse_name(value: str) -> str:
    """Return the name or raise FieldError if it is too long."""
    if len(value) > MAX_NAME_LENGTH:
        raise FieldError(f"longer than {MAX_NAME_LENGTH} characters")
    return value


def parse_email(value: str) -> str:
    """Return the lower-cased email or raise FieldError if it is not valid."""
    email = value.lower()
    if not (email.isascii() and len(email) <= MAX_EMAIL_LENGTH and EMAIL_PATTERN.fullmatch(email)):
        raise FieldError(f"{shown(value)} is not a valid email address")
    return email


def parse_monthly_income(value: str) -> Decimal:
    """Return a positive amount with up to 2 decimals or raise FieldError."""
    if not AMOUNT_PATTERN.fullmatch(value) or Decimal(value) <= 0:
        raise FieldError(f"{shown(value)} is not a positive amount (digits, up to 2 decimals)")
    return Decimal(value)


def whole_number_between(low: int, high: int) -> Callable[[str], int]:
    """Return a parser that accepts whole numbers from `low` to `high`."""

    def parse(value: str) -> int:
        if not WHOLE_NUMBER_PATTERN.fullmatch(value) or not low <= int(value) <= high:
            raise FieldError(f"{shown(value)} is not a whole number from {low} to {high}")
        return int(value)

    return parse


def parse_employment_status(value: str) -> str:
    """Map any casing or punctuation to the canonical employment value."""
    status = EMPLOYMENT_BY_KEY.get(re.sub(r"[^a-z]", "", value.lower()))
    if status is None:
        raise FieldError(f"{shown(value)} is not one of {', '.join(EMPLOYMENT_STATUSES)}")
    return status


PARSERS: Mapping[str, Callable[[str], Any]] = {
    "user_id": parse_user_id,
    "name": parse_name,
    "email": parse_email,
    "monthly_income": parse_monthly_income,
    "credit_score": whole_number_between(CREDIT_SCORE_MIN, CREDIT_SCORE_MAX),
    "employment_status": parse_employment_status,
    "age": whole_number_between(AGE_MIN, AGE_MAX),
}


def parse_field(column: str, value: str) -> Any:
    """Trim, reject blanks and control characters (Postgres text cannot hold NUL), then parse."""
    value = value.strip()
    if not value:
        raise FieldError("missing")
    if any(ord(c) < FIRST_PRINTABLE or ord(c) == DELETE_CHARACTER for c in value):
        raise FieldError("contains a control character")
    return PARSERS[column](value)


def validate_record(record: Record, layout: ColumnLayout) -> UserRow | Reject:
    """Return the normalised row, or one reject listing every broken field."""
    if len(record.fields) != len(layout.columns):
        reason = f"expected {len(layout.columns)} fields, got {len(record.fields)}"
        return make_reject(record.line_no, reason, record.raw)
    parsed: dict[str, Any] = {}
    problems: list[str] = []
    for column, position in layout.positions.items():
        try:
            parsed[column] = parse_field(column, record.fields[position])
        except FieldError as error:
            problems.append(f"{column}: {error}")
    if problems:
        return make_reject(record.line_no, "; ".join(problems), record.raw)
    return UserRow(**parsed)


def validate_rows(records: Iterable[Record | Reject], layout: ColumnLayout) -> ValidationResult:
    """Split records into valid rows and rejects; a repeated `user_id` keeps its first row."""
    result = ValidationResult()
    first_line: dict[uuid.UUID, int] = {}
    for record in records:
        if isinstance(record, Reject):
            result.rejects.append(record)
            continue
        outcome = validate_record(record, layout)
        if isinstance(outcome, UserRow):
            outcome = reject_if_duplicate(outcome, record, first_line)
        if isinstance(outcome, UserRow):
            result.valid.append(outcome)
        else:
            result.rejects.append(outcome)
    return result


def reject_if_duplicate(
    row: UserRow, record: Record, first_line: dict[uuid.UUID, int]
) -> UserRow | Reject:
    """Keep the first row for a user_id; later ones become rejects."""
    seen_at = first_line.setdefault(row.user_id, record.line_no)
    if seen_at == record.line_no:
        return row
    return make_reject(record.line_no, f"user_id: duplicate of line {seen_at}", record.raw)


def validate_file(text: str) -> tuple[ColumnLayout, ValidationResult]:
    """Validate a whole CSV text whose first record is the header."""
    records = read_records(text)
    header = next(records, None)
    if header is None:
        raise HeaderError("file is empty")
    if isinstance(header, Reject):
        raise HeaderError(f"header row is not valid CSV ({header.reason})")
    layout = check_header(header.fields)
    return layout, validate_rows(records, layout)
