"""scripts/gen_synthetic_users.py: determinism, validity under the real rules, safe emails."""

import csv
from pathlib import Path

import pytest

from lambdas.shared.validation import validate_file
from scripts.gen_synthetic_users import (
    EMAIL_DOMAIN,
    HEADER,
    main,
    parse_args,
    user_rows,
    write_csv,
)

ROWS = 2_000


def test_same_seed_gives_identical_rows() -> None:
    assert list(user_rows(50, seed=7)) == list(user_rows(50, seed=7))


def test_different_seed_gives_different_rows() -> None:
    assert list(user_rows(50, seed=7)) != list(user_rows(50, seed=8))


def test_every_email_uses_the_reserved_domain() -> None:
    assert all(row[2].endswith(f"@{EMAIL_DOMAIN}") for row in user_rows(ROWS, seed=1))


def test_user_ids_are_unique() -> None:
    ids = [row[0] for row in user_rows(ROWS, seed=1)]
    assert len(set(ids)) == ROWS


def test_file_passes_the_production_validation(tmp_path: Path) -> None:
    target = tmp_path / "users.csv"
    write_csv(target, ROWS, seed=3)
    _, result = validate_file(target.read_text(encoding="utf-8"))
    assert (len(result.valid), len(result.rejects)) == (ROWS, 0)


def test_file_has_header_and_requested_row_count(tmp_path: Path) -> None:
    target = tmp_path / "users.csv"
    write_csv(target, 10, seed=3)
    with target.open(newline="") as handle:
        records = list(csv.reader(handle))
    assert (tuple(records[0]), len(records) - 1) == (HEADER, 10)


def test_main_writes_the_requested_file(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "users.csv"
    assert main(["--rows", "5", "--output", str(target)]) == 0
    assert target.exists()


def test_rows_below_one_are_refused() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--rows", "0"])
