"""Every row that validation accepts also satisfies the `users` CHECK constraints on PostgreSQL 16.

load-chunk COPYs a whole chunk in one statement, so one accepted row that the database refuses
would fail every row of its chunk. These tests insert accepted rows in a single statement, so any
single violation fails the test, and show that the same rows without validation are refused.
"""

import csv
import io
import os
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from pg8000.exceptions import DatabaseError

from lambdas.shared.batches import create_batch
from lambdas.shared.validation import (
    MAX_EMAIL_LENGTH,
    MAX_NAME_LENGTH,
    REQUIRED_COLUMNS,
    UserRow,
    validate_file,
)

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set")

SAMPLE_CSV = Path(__file__).resolve().parents[2] / "data" / "users.csv"
LONG_LOCAL_PART = "a" * 64
LONG_EMAIL = f"{LONG_LOCAL_PART}@{'b' * (MAX_EMAIL_LENGTH - len(LONG_LOCAL_PART) - 4)}.in"

INSERT_USERS = """
    INSERT INTO users (user_id, name, email, monthly_income, credit_score, employment_status, age,
                       batch_id)
    SELECT u.*, CAST(:batch_id AS uuid)
    FROM unnest(CAST(:ids AS uuid[]), CAST(:names AS text[]), CAST(:emails AS text[]),
                CAST(:incomes AS numeric[]), CAST(:scores AS smallint[]),
                CAST(:statuses AS text[]), CAST(:ages AS smallint[])) AS u
"""


def boundary_csv() -> str:
    rows = [
        (uuid.uuid4(), "A", "a@b.co", "0.01", "300", "Salaried", "18"),
        (
            uuid.uuid4(),
            "Ö" * MAX_NAME_LENGTH,
            LONG_EMAIL,
            "9999999999.99",
            "900",
            "BUSINESS",
            "100",
        ),
        (
            uuid.uuid4(),
            '  Rao, "Asha"  ',
            "  Asha.Rao+x@Example.INVALID ",
            "25000",
            "650",
            " self employed ",
            "22",
        ),
        (
            str(uuid.uuid4()).upper(),
            "Ölçü Ñandú",
            "o.n@sub.example.invalid",
            "150000.5",
            "800",
            "self_employed",
            "50",
        ),
        (uuid.uuid4(), "Too Old", "old@example.invalid", "30000", "700", "Salaried", "101"),
        (uuid.uuid4(), "Bad Score", "score@example.invalid", "30000", "950", "Salaried", "30"),
    ]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(REQUIRED_COLUMNS)
    writer.writerows(rows)
    return out.getvalue()


def as_columns(rows: Sequence[UserRow]) -> dict[str, list[str]]:
    return {
        "ids": [str(r.user_id) for r in rows],
        "names": [r.name for r in rows],
        "emails": [r.email for r in rows],
        "incomes": [str(r.monthly_income) for r in rows],
        "scores": [str(r.credit_score) for r in rows],
        "statuses": [r.employment_status for r in rows],
        "ages": [str(r.age) for r in rows],
    }


def insert_users(conn: Any, columns: dict[str, list[str]]) -> int:
    conn.run(INSERT_USERS, batch_id=str(create_batch(conn)), **columns)
    count: int = conn.run("SELECT count(*) FROM users")[0][0]
    return count


def test_accepted_boundary_rows_satisfy_every_check(connect_db: Callable[[], Any]) -> None:
    _, result = validate_file(boundary_csv())
    assert len(result.valid) == 4
    assert [r.line_no for r in result.rejects] == [6, 7]
    conn = connect_db()
    assert insert_users(conn, as_columns(result.valid)) == 4
    stored = conn.run("SELECT email, employment_status FROM users WHERE name = 'Rao, \"Asha\"'")
    assert stored == [["asha.rao+x@example.invalid", "Self-Employed"]]


@pytest.mark.parametrize(
    ("column", "raw_value", "constraint"),
    [
        ("emails", "Asha.Rao@Example.INVALID", "users_email_check"),
        ("statuses", " self employed ", "users_employment_status_check"),
        ("scores", "950", "users_credit_score_check"),
        ("ages", "101", "users_age_check"),
    ],
)
def test_values_validation_changes_or_rejects_are_refused_by_the_database(
    connect_db: Callable[[], Any], column: str, raw_value: str, constraint: str
) -> None:
    columns = {
        "ids": [str(uuid.uuid4())],
        "names": ["Asha Rao"],
        "emails": ["asha.rao@example.invalid"],
        "incomes": ["25000"],
        "scores": ["650"],
        "statuses": ["Salaried"],
        "ages": ["22"],
    }
    columns[column] = [raw_value]
    conn = connect_db()
    batch_id = str(create_batch(conn))
    with pytest.raises(DatabaseError, match=constraint):
        conn.run(INSERT_USERS, batch_id=batch_id, **columns)


@pytest.mark.skipif(not SAMPLE_CSV.exists(), reason="data/users.csv not present (gitignored)")
def test_every_sample_row_is_accepted_and_stored(connect_db: Callable[[], Any]) -> None:
    _, result = validate_file(SAMPLE_CSV.read_bytes().decode("utf-8"))
    assert result.rejects == []
    assert insert_users(connect_db(), as_columns(result.valid)) == len(result.valid) == 10_000
