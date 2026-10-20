"""lambdas/shared/validation.py: header layout, CSV records, field rules and the fixture files."""

import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from lambdas.shared.validation import (
    MAX_EMAIL_LENGTH,
    MAX_NAME_LENGTH,
    MAX_RAW_LENGTH,
    REQUIRED_COLUMNS,
    FieldError,
    HeaderError,
    Record,
    Reject,
    UserRow,
    check_header,
    parse_field,
    read_records,
    validate_file,
    validate_record,
    validate_rows,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
LAYOUT = check_header(REQUIRED_COLUMNS)
USER_A = "00000000-0000-4000-8000-000000000001"
USER_B = "00000000-0000-4000-8000-000000000002"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_bytes().decode("utf-8")


def record(*fields: str, line_no: int = 2) -> Record:
    return Record(line_no=line_no, fields=list(fields), raw=",".join(fields))


def good_fields(user_id: str = USER_A) -> list[str]:
    return [user_id, "Asha Rao", "asha@example.invalid", "30000", "700", "Salaried", "30"]


def test_header_in_file_order_maps_each_column_to_its_position() -> None:
    assert LAYOUT.columns == REQUIRED_COLUMNS
    assert dict(LAYOUT.positions) == {c: i for i, c in enumerate(REQUIRED_COLUMNS)}
    assert LAYOUT.ignored == ()


def test_header_ignores_bom_case_spaces_and_order() -> None:
    fields = ["﻿ AGE ", "Name", "EMAIL", "user_id", "credit_score", "Employment_Status"]
    layout = check_header([*fields, "monthly_income"])
    assert layout.positions["age"] == 0
    assert layout.positions["monthly_income"] == len(fields)


def test_header_keeps_unknown_columns_and_reports_them_as_ignored() -> None:
    layout = check_header([*REQUIRED_COLUMNS, "City"])
    assert layout.ignored == ("city",)
    row = validate_record(record(*good_fields(), "Pune"), layout)
    assert isinstance(row, UserRow)


def test_header_error_lists_every_missing_and_repeated_column() -> None:
    with pytest.raises(HeaderError, match=r"missing columns: age; repeated columns: email"):
        check_header(
            [
                "user_id",
                "name",
                "email",
                "email",
                "monthly_income",
                "credit_score",
                "employment_status",
            ]
        )


def test_empty_header_is_missing_all_columns() -> None:
    with pytest.raises(HeaderError, match="missing columns: user_id, name, email"):
        check_header([])


def test_layout_rebuilt_from_its_columns_is_identical() -> None:
    layout = check_header(["age", *REQUIRED_COLUMNS[:-1], "city"])
    assert check_header(layout.columns) == layout


def test_record_line_numbers_count_physical_lines() -> None:
    text = 'a,"two\r\nlines"\r\n\r\nb,c\r\n'
    records = list(read_records(text, first_line_no=10))
    assert [(r.line_no, r.raw) for r in records] == [(10, 'a,"two\r\nlines"'), (13, "b,c")]
    assert isinstance(records[0], Record)
    assert records[0].fields == ["a", "two\r\nlines"]


def test_malformed_record_becomes_a_reject_and_reading_continues() -> None:
    records = list(read_records('a,"b"c\nd,e\n'))
    assert isinstance(records[0], Reject)
    assert records[0].reason.startswith("malformed CSV:")
    assert records[0].line_no == 1
    assert records[1] == Record(line_no=2, fields=["d", "e"], raw="d,e")


def test_unclosed_quote_at_end_of_text_is_one_reject() -> None:
    records = list(read_records('a,b\n"open,c\nd,e\n'))
    assert len(records) == 2
    assert isinstance(records[1], Reject)
    assert records[1].reason == "malformed CSV: unexpected end of data"


def test_reject_raw_text_is_truncated() -> None:
    long_line = "x" * (MAX_RAW_LENGTH * 2)
    rejected = validate_record(record(long_line), LAYOUT)
    assert isinstance(rejected, Reject)
    assert len(rejected.raw) == MAX_RAW_LENGTH


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    [
        (
            "user_id",
            " 00000000-0000-4000-8000-00000000000A ",
            uuid.UUID("00000000-0000-4000-8000-00000000000a"),
        ),
        ("name", "  Rao, Asha  ", "Rao, Asha"),
        ("name", "Ölçü Ñandú", "Ölçü Ñandú"),
        ("name", "n" * MAX_NAME_LENGTH, "n" * MAX_NAME_LENGTH),
        ("email", " Asha.Rao+loans@Example.Invalid ", "asha.rao+loans@example.invalid"),
        ("monthly_income", "25000", Decimal("25000")),
        ("monthly_income", "25000.5", Decimal("25000.5")),
        ("monthly_income", "9999999999.99", Decimal("9999999999.99")),
        ("credit_score", "300", 300),
        ("credit_score", "900", 900),
        ("age", "18", 18),
        ("age", "100", 100),
        ("employment_status", "Salaried", "Salaried"),
        ("employment_status", " self employed ", "Self-Employed"),
        ("employment_status", "SELF_EMPLOYED", "Self-Employed"),
        ("employment_status", "business", "Business"),
    ],
)
def test_valid_values_are_normalised(column: str, value: str, expected: object) -> None:
    assert parse_field(column, value) == expected


def test_uuid_is_returned_in_canonical_form() -> None:
    parsed = parse_field("user_id", USER_A.upper())
    assert str(parsed) == USER_A


def test_longest_allowed_email_is_accepted() -> None:
    local = "a" * 64
    domain = "b" * (MAX_EMAIL_LENGTH - len(local) - len("@.in")) + ".in"
    assert len(f"{local}@{domain}") == MAX_EMAIL_LENGTH
    assert parse_field("email", f"{local}@{domain}") == f"{local}@{domain}"


@pytest.mark.parametrize(
    ("column", "value", "reason"),
    [
        ("age", "", "missing"),
        ("name", " \t ", "missing"),
        ("name", "Asha\x00Rao", "contains a control character"),
        ("name", "Asha\nRao", "contains a control character"),
        ("name", "Asha\x7fRao", "contains a control character"),
        ("name", "n" * (MAX_NAME_LENGTH + 1), "longer than"),
        ("user_id", "not-a-uuid", "is not a UUID"),
        ("user_id", "{00000000-0000-4000-8000-000000000001}", "is not a UUID"),
        ("user_id", "00000000000040008000000000000001", "is not a UUID"),
        ("email", "asha.example.invalid", "not a valid email"),
        ("email", "asha@localhost", "not a valid email"),
        ("email", "asha@example..invalid", "not a valid email"),
        ("email", "a@b@example.invalid", "not a valid email"),
        ("email", "asha rao@example.invalid", "not a valid email"),
        ("email", "äsha@example.invalid", "not a valid email"),
        ("email", "a" * MAX_EMAIL_LENGTH + "@example.invalid", "not a valid email"),
        ("monthly_income", "25,000", "not a positive amount"),
        ("monthly_income", "₹25000", "not a positive amount"),
        ("monthly_income", "-5", "not a positive amount"),
        ("monthly_income", "+5", "not a positive amount"),
        ("monthly_income", "0", "not a positive amount"),
        ("monthly_income", "0.00", "not a positive amount"),
        ("monthly_income", "1.234", "not a positive amount"),
        ("monthly_income", "1e5", "not a positive amount"),
        ("monthly_income", "NaN", "not a positive amount"),
        ("monthly_income", "12345678901", "not a positive amount"),
        ("credit_score", "299", "not a whole number from 300 to 900"),
        ("credit_score", "901", "not a whole number from 300 to 900"),
        ("credit_score", "750.0", "not a whole number"),
        ("credit_score", "7_50", "not a whole number"),
        ("credit_score", "\u0667\u0665\u0660", "not a whole number"),
        ("credit_score", "1" * 5000, "not a whole number"),
        ("age", "17", "not a whole number from 18 to 100"),
        ("age", "101", "not a whole number from 18 to 100"),
        ("employment_status", "Student", "is not one of Salaried, Self-Employed, Business"),
        ("employment_status", "Self Employed Professional", "is not one of"),
    ],
)
def test_invalid_values_are_rejected_with_a_reason(column: str, value: str, reason: str) -> None:
    with pytest.raises(FieldError, match=reason):
        parse_field(column, value)


def test_long_values_are_shortened_in_the_reason() -> None:
    with pytest.raises(FieldError) as raised:
        parse_field("credit_score", "9" * 500)
    assert len(str(raised.value)) < 100
    assert "…" in str(raised.value)


def test_wrong_field_count_is_rejected_before_field_rules() -> None:
    rejected = validate_record(record(USER_A, "Asha"), LAYOUT)
    assert rejected == Reject(line_no=2, reason="expected 7 fields, got 2", raw=f"{USER_A},Asha")


def test_every_broken_field_is_listed_in_column_order() -> None:
    fields = ["bad", "Asha", "asha@example.invalid", "30000", "950", "Retired", ""]
    rejected = validate_record(record(*fields), LAYOUT)
    assert isinstance(rejected, Reject)
    assert rejected.reason == (
        "user_id: 'bad' is not a UUID; "
        "credit_score: '950' is not a whole number from 300 to 900; "
        "employment_status: 'Retired' is not one of Salaried, Self-Employed, Business; "
        "age: missing"
    )


def test_valid_record_becomes_a_typed_row() -> None:
    row = validate_record(record(*good_fields()), LAYOUT)
    assert row == UserRow(
        user_id=uuid.UUID(USER_A),
        name="Asha Rao",
        email="asha@example.invalid",
        monthly_income=Decimal("30000"),
        credit_score=700,
        employment_status="Salaried",
        age=30,
    )


def test_duplicate_user_id_keeps_the_first_row() -> None:
    first = record(*good_fields(), line_no=2)
    other = record(*good_fields(USER_B), line_no=3)
    again = record(*good_fields(USER_A.upper()), line_no=7)
    result = validate_rows([first, other, again], LAYOUT)
    assert [str(r.user_id) for r in result.valid] == [USER_A, USER_B]
    assert [(r.line_no, r.reason) for r in result.rejects] == [(7, "user_id: duplicate of line 2")]


def test_rejected_row_does_not_claim_its_user_id() -> None:
    bad = record(USER_A, "Asha", "asha@example.invalid", "30000", "100", "Salaried", "30")
    good = record(*good_fields(), line_no=3)
    result = validate_rows([bad, good], LAYOUT)
    assert len(result.valid) == 1
    assert [r.line_no for r in result.rejects] == [2]


def test_parse_rejects_pass_through_validate_rows() -> None:
    parse_reject = Reject(line_no=5, reason="malformed CSV: x", raw="x")
    result = validate_rows([parse_reject], LAYOUT)
    assert result.rejects == [parse_reject]
    assert result.valid == []


def test_good_fixture_loads_every_row() -> None:
    _, result = validate_file(fixture_text("good_users.csv"))
    assert len(result.valid) == 5
    assert result.rejects == []
    assert {r.employment_status for r in result.valid} == {"Salaried", "Self-Employed", "Business"}


def test_bom_crlf_reordered_fixture_normalises_and_numbers_lines() -> None:
    layout, result = validate_file(fixture_text("bom_crlf_quoted.csv"))
    assert layout.columns[0] == "age"
    rohan, arun = result.valid
    assert (rohan.name, rohan.email) == ("Mehta, Rohan", "rohan.mehta@example.invalid")
    assert (rohan.employment_status, rohan.monthly_income) == ("Self-Employed", Decimal("55000.50"))
    assert str(rohan.user_id) == "00000000-0000-4000-8000-000000000011"
    assert arun.employment_status == "Business"
    assert [(r.line_no, r.reason) for r in result.rejects] == [
        (3, "name: contains a control character")
    ]


def test_malformed_fixture_reports_one_reason_per_bad_line() -> None:
    _, result = validate_file(fixture_text("malformed_users.csv"))
    reasons = {r.line_no: r.reason for r in result.rejects}
    assert len(result.valid) == 1
    assert sorted(reasons) == list(range(2, 12))
    assert reasons[2] == "age: missing"
    assert reasons[5].startswith("monthly_income: '25,000'")
    assert reasons[9] == "expected 7 fields, got 5"
    assert reasons[10].count(";") == 3
    assert reasons[11].startswith("malformed CSV:")


def test_duplicate_fixture_keeps_first_copy() -> None:
    _, result = validate_file(fixture_text("duplicate_ids.csv"))
    assert [r.name for r in result.valid] == ["First Copy", "Other User"]
    assert [(r.line_no, r.reason) for r in result.rejects] == [(4, "user_id: duplicate of line 2")]


def test_header_only_fixture_has_no_rows() -> None:
    _, result = validate_file(fixture_text("header_only.csv"))
    assert result.valid == []
    assert result.rejects == []


def test_header_mismatch_fixture_is_refused() -> None:
    text = fixture_text("header_mismatch.csv")
    with pytest.raises(HeaderError, match="missing columns: age; repeated columns: email"):
        validate_file(text)


def test_empty_fixture_is_refused() -> None:
    text = fixture_text("empty.csv")
    with pytest.raises(HeaderError, match="file is empty"):
        validate_file(text)


def test_unparseable_header_is_refused() -> None:
    with pytest.raises(HeaderError, match="header row is not valid CSV"):
        validate_file('"user_id,name\n')
