"""Reject report: problem names from real validator reasons, grouping, spreadsheet-safe CSV."""

import csv
import io

import pytest

from lambdas.shared.reject_report import (
    CSV_HEADER,
    problem_of,
    rejects_csv,
    spreadsheet_safe,
    summarise,
)
from lambdas.shared.validation import REQUIRED_COLUMNS, Record, check_header, validate_rows

GOOD_ID = "5b0f3f2e-8d1a-4a51-9a64-3f5ad7b1c001"


def reasons_for(*rows: list[str]) -> list[str]:
    records = [Record(i + 2, fields, ",".join(fields)) for i, fields in enumerate(rows)]
    result = validate_rows(records, check_header(list(REQUIRED_COLUMNS)))
    return [reject.reason for reject in result.rejects]


def test_problem_names_follow_the_validator_reasons() -> None:
    good = [GOOD_ID, "A", "a@example.invalid", "50000", "700", "Salaried", "30"]
    reasons = reasons_for(
        [*good[:6], "12"],
        ["not-a-uuid", *good[1:4], "990", *good[5:]],
        good[:3],
        good,
        good,
    )

    parts = [problem_of(part) for reason in reasons for part in reason.split("; ")]

    assert parts == [
        "age",
        "user_id",
        "credit_score",
        "wrong number of fields",
        "duplicate user_id",
    ]


@pytest.mark.parametrize(
    ("part", "problem"),
    [
        ("malformed CSV: unexpected end of data", "malformed CSV"),
        (
            "employment_status: 'x' is not one of Salaried, Self-Employed, Business",
            "employment_status",
        ),
        ("something new", "other"),
        ("expected 7 fields", "other"),
    ],
)
def test_problem_of_whole_row_and_unknown_reasons(part: str, problem: str) -> None:
    assert problem_of(part) == problem


def test_summary_counts_a_row_once_per_problem_and_keeps_the_first_example() -> None:
    rejects = [
        (5, "age: '12' is bad; email: 'x' is bad"),
        (3, "age: '7' is bad"),
        (9, "expected 7 fields, got 3"),
        (11, "email: 'z' is bad"),
    ]

    summary = summarise(rejects)

    assert summary == [
        {"problem": "age", "rows": 2, "first_line": 5, "example": "age: '12' is bad"},
        {"problem": "email", "rows": 2, "first_line": 5, "example": "email: 'x' is bad"},
        {
            "problem": "wrong number of fields",
            "rows": 1,
            "first_line": 9,
            "example": "expected 7 fields, got 3",
        },
    ]


def test_a_value_that_looks_like_a_separator_does_not_count_its_row_twice() -> None:
    summary = summarise([(4, "email: 'x; email: y' is not a valid email address")])

    assert [(group["problem"], group["rows"]) for group in summary] == [("email", 1)]
    assert summary[0]["example"] == "email: 'x"


def test_summary_of_no_rejects_is_empty() -> None:
    assert summarise([]) == []


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_formula_prefixes_are_neutralised(prefix: str) -> None:
    assert spreadsheet_safe(prefix + "SUM(A1)") == "'" + prefix + "SUM(A1)"


@pytest.mark.parametrize("value", ["plain", "a=b", "", None])
def test_other_text_is_unchanged(value: str | None) -> None:
    assert spreadsheet_safe(value) == (value or "")


def test_csv_round_trips_quotes_commas_and_newlines() -> None:
    raw = 'id,"Doe, J",a@b.c,1,2,Salaried,"line\nbreak"'

    text = rejects_csv([(4, "age: missing", raw), (8, "=cmd", None)])

    rows = list(csv.reader(io.StringIO(text, newline="")))
    assert rows == [list(CSV_HEADER), ["4", "age: missing", raw], ["8", "'=cmd", ""]]
