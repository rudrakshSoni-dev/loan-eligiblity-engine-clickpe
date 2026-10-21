"""Workflow C compose and recipient guard on real PostgreSQL 16: the exported SQL and Code nodes.

The nodes are read from the exported workflow JSON and chained as n8n chains them, each fed with the
previous output, so a change made in the editor and exported is what the tests check.
"""

import json
import os
import subprocess
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from pg8000.exceptions import DatabaseError

from tests.workflow_b_helpers import (
    NODE_BINARY,
    add_product,
    new_batch,
    node_query,
    run_code_node,
    single_row,
)
from tests.workflow_c_helpers import WORKFLOW_C

pytestmark = [
    pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set"),
    pytest.mark.skipif(NODE_BINARY is None, reason="node not installed"),
]

READ_BATCH_NODE = "Check · Read batch_id"
CONFIG_LOAD_NODE = "Config · Load settings"
CONFIG_VALIDATE_NODE = "Config · Validate settings"
CLAIM_NODE = "Claim · matched to notifying"
SELECT_NODE = "Compose · Select recipients"
BUILD_NODE = "Compose · Build emails"
GUARD_NODE = "Guard · Recipients are test inboxes"
RELEASE_NODE = "Release · notifying back to matched"
FAIL_NODE = "Fail · Mark batch failed (Notify)"

BATCH_PARAMS = {"$1": ":batch_id"}
SELECT_PARAMS = {"$1": ":batch_id", "$2": ":max_emails"}
RELEASE_PARAMS = {"$1": ":batch_id", "$2": ":composed", "$3": ":waiting", "$4": ":dry_run"}
FAIL_PARAMS = {"$1": ":batch_id", "$2": ":message"}

ALIASES = ["mrrssoni12@gmail.com", "mrrssoni12+one@gmail.com", "mrrssoni12+two@gmail.com"]
FIRST_USER = uuid.UUID("00000000-0000-4000-8000-000000000001")
SECOND_USER = uuid.UUID("00000001-0000-4000-8000-000000000001")
THIRD_USER = uuid.UUID("00000002-0000-4000-8000-000000000001")
FOURTH_USER = uuid.UUID("00000003-0000-4000-8000-000000000001")


def node_sql(name: str, placeholders: dict[str, str]) -> str:
    return node_query(name, placeholders, WORKFLOW_C)


def code(name: str, item: Any, nodes: dict[str, list[dict[str, Any]]] | None = None) -> Any:
    return run_code_node(name, item, nodes, WORKFLOW_C)


def set_config(conn: Any, key: str, value: Any) -> None:
    conn.run(
        "UPDATE app_config SET value = CAST(:value AS jsonb) WHERE key = :key",
        key=key,
        value=json.dumps(value),
    )


def validated_config(conn: Any, batch_id: uuid.UUID) -> dict[str, Any]:
    loaded = single_row(conn, conn.run(node_sql(CONFIG_LOAD_NODE, {})))
    output = code(CONFIG_VALIDATE_NODE, loaded, {READ_BATCH_NODE: [{"batch_id": str(batch_id)}]})
    config: dict[str, Any] = output[0]["json"]
    return config


def add_user_with_id(
    conn: Any, batch_id: uuid.UUID, user_id: uuid.UUID, name: str, email: str
) -> None:
    conn.run(
        "INSERT INTO users (user_id, name, email, monthly_income, credit_score,"
        " employment_status, age, batch_id) VALUES (:id, :name, :email, 50000, 720,"
        " 'Salaried', 30, :batch)",
        id=user_id,
        name=name,
        email=email,
        batch=batch_id,
    )


def add_match(
    conn: Any,
    batch_id: uuid.UUID,
    user_id: uuid.UUID,
    product_id: int,
    reason: str = "meets every published criterion",
    notified: bool = False,
) -> None:
    conn.run(
        "INSERT INTO matches (user_id, product_id, stage, reason, batch_id, notified_at)"
        " VALUES (:u, :p, 'rules', :reason, :b, CASE WHEN :notified THEN now() END)",
        u=user_id,
        p=product_id,
        reason=reason,
        b=batch_id,
        notified=notified,
    )


def claim(conn: Any, batch_id: uuid.UUID) -> dict[str, Any]:
    return single_row(conn, conn.run(node_sql(CLAIM_NODE, BATCH_PARAMS), batch_id=batch_id))


def select_recipients(conn: Any, batch_id: uuid.UUID, max_emails: int = 5) -> dict[str, Any]:
    rows = conn.run(node_sql(SELECT_NODE, SELECT_PARAMS), batch_id=batch_id, max_emails=max_emails)
    return single_row(conn, rows)


def build_emails(conn: Any, batch_id: uuid.UUID, selected: dict[str, Any]) -> dict[str, Any]:
    config = validated_config(conn, batch_id)
    output = code(BUILD_NODE, selected, {CONFIG_VALIDATE_NODE: [config]})
    built: dict[str, Any] = output[0]["json"]
    return built


def guard(
    conn: Any, batch_id: uuid.UUID, built: dict[str, Any], config: dict[str, Any] | None = None
) -> dict[str, Any]:
    settings = config if config is not None else validated_config(conn, batch_id)
    output = code(GUARD_NODE, built, {CONFIG_VALIDATE_NODE: [settings]})
    guarded: dict[str, Any] = output[0]["json"]
    return guarded


def release(conn: Any, batch_id: uuid.UUID, guarded: dict[str, Any]) -> dict[str, Any]:
    rows = conn.run(
        node_sql(RELEASE_NODE, RELEASE_PARAMS),
        batch_id=batch_id,
        composed=len(guarded["emails"]),
        waiting=guarded["users_waiting"],
        dry_run=guarded["dry_run"],
    )
    return single_row(conn, rows)


def run_chain(conn: Any, batch_id: uuid.UUID, max_emails: int = 5) -> dict[str, Any]:
    assert claim(conn, batch_id)["claimed"] == 1
    selected = select_recipients(conn, batch_id, max_emails)
    guarded = guard(conn, batch_id, build_emails(conn, batch_id, selected))
    return {**guarded, "released": release(conn, batch_id, guarded)}


def batch_status(conn: Any, batch_id: uuid.UUID) -> str:
    return str(conn.run("SELECT status FROM upload_batches WHERE id = :id", id=batch_id)[0][0])


def unnotified(conn: Any, batch_id: uuid.UUID) -> int:
    rows = conn.run(
        "SELECT count(*) FROM matches WHERE batch_id = :id AND notified_at IS NULL", id=batch_id
    )
    return int(rows[0][0])


@pytest.fixture
def conn(connect_db: Callable[[], Any]) -> Any:
    return connect_db()


@pytest.fixture
def matched_batch(conn: Any) -> uuid.UUID:
    return new_batch(conn, "matched")


def two_users_three_offers(conn: Any, batch_id: uuid.UUID) -> dict[str, int]:
    cheap = add_product(
        conn,
        "Cheap Loan",
        interest_rate_min=10.5,
        interest_rate_max=14,
        source_url="https://bank.example/cheap",
    )
    dear = add_product(conn, "Dear Loan", interest_rate_min=12, interest_rate_max=12)
    other = add_product(conn, "Other Loan", interest_rate_min=11, interest_rate_max=18)
    add_user_with_id(conn, batch_id, FIRST_USER, "Asha Rao", "asha@example.invalid")
    add_user_with_id(conn, batch_id, SECOND_USER, "Ben Roy", "ben@example.invalid")
    add_match(conn, batch_id, FIRST_USER, dear)
    add_match(conn, batch_id, FIRST_USER, cheap)
    add_match(conn, batch_id, SECOND_USER, other)
    return {"cheap": cheap, "dear": dear, "other": other}


def test_migration_seeds_safe_defaults(conn: Any, matched_batch: uuid.UUID) -> None:
    config = validated_config(conn, matched_batch)
    assert config == {
        "batch_id": str(matched_batch),
        "dry_run": True,
        "aliases": ALIASES,
        "max_emails": 5,
    }


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("dry_run", "yes"),
        ("dry_run", 1),
        ("max_emails_per_run", 0),
        ("max_emails_per_run", -3),
        ("max_emails_per_run", "5"),
        ("max_emails_per_run", 2.5),
        ("max_emails_per_run", 10000),
        ("test_inbox_aliases", []),
        ("test_inbox_aliases", "a@b.co"),
    ],
)
def test_app_config_check_rejects_malformed_values(conn: Any, key: str, value: Any) -> None:
    with pytest.raises(DatabaseError, match="check constraint"):
        set_config(conn, key, value)


def test_app_config_accepts_valid_values_and_refuses_unknown_keys(conn: Any) -> None:
    set_config(conn, "dry_run", False)
    set_config(conn, "max_emails_per_run", 9999)
    set_config(conn, "test_inbox_aliases", ["only@example.com"])
    with pytest.raises(DatabaseError, match="check constraint"):
        conn.run(
            "INSERT INTO app_config (key, value, description) VALUES ('send_to_real', 'true', 'x')"
        )


def test_app_config_updated_at_moves_on_change(conn: Any) -> None:
    before = conn.run("SELECT updated_at FROM app_config WHERE key = 'dry_run'")[0][0]
    conn.run("SELECT pg_sleep(0.01)")
    set_config(conn, "dry_run", False)
    after = conn.run("SELECT updated_at FROM app_config WHERE key = 'dry_run'")[0][0]
    assert after > before


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({}, "dry_run must be true or false"),
        ({"dry_run": "true", "test_inbox_aliases": ALIASES, "max_emails_per_run": 5}, "dry_run"),
        (
            {"dry_run": True, "test_inbox_aliases": [], "max_emails_per_run": 5},
            "test_inbox_aliases",
        ),
        (
            {"dry_run": True, "test_inbox_aliases": ["not an email"], "max_emails_per_run": 5},
            "test_inbox_aliases",
        ),
        (
            {"dry_run": True, "test_inbox_aliases": ["a@b.co,c@d.co"], "max_emails_per_run": 5},
            "test_inbox_aliases",
        ),
        ({"dry_run": True, "test_inbox_aliases": ALIASES, "max_emails_per_run": 0}, "max_emails"),
        ({"dry_run": True, "test_inbox_aliases": ALIASES, "max_emails_per_run": "5"}, "max_emails"),
    ],
)
def test_validate_node_fails_closed_on_missing_or_malformed_settings(
    config: dict[str, Any], message: str
) -> None:
    with pytest.raises(subprocess.CalledProcessError) as raised:
        code(
            CONFIG_VALIDATE_NODE,
            {"config": config},
            {READ_BATCH_NODE: [{"batch_id": str(uuid.uuid4())}]},
        )
    assert "app_config invalid" in raised.value.stderr
    assert message in raised.value.stderr


def test_validate_node_normalises_and_deduplicates_aliases() -> None:
    config = {
        "dry_run": False,
        "test_inbox_aliases": [" A@Example.com ", "a@example.com", "b@example.com"],
        "max_emails_per_run": 3,
    }
    output = code(CONFIG_VALIDATE_NODE, {"config": config}, {READ_BATCH_NODE: [{"batch_id": "b"}]})
    assert output[0]["json"]["aliases"] == ["a@example.com", "b@example.com"]


@pytest.mark.parametrize("value", [None, "", "not-a-uuid", "9d278e88-0000-0000-0000-00000000000g"])
def test_read_batch_rejects_anything_but_a_uuid(value: Any) -> None:
    with pytest.raises(subprocess.CalledProcessError) as raised:
        code(READ_BATCH_NODE, {"batch_id": value})
    assert "batch_id must be a UUID" in raised.value.stderr


def test_read_batch_lowercases_and_ignores_other_fields() -> None:
    upper = "9D278E88-0000-4000-8000-00000000000A"
    output = code(READ_BATCH_NODE, {"batch_id": f" {upper} ", "run_id": "17", "final_matches": 5})
    assert output == [{"json": {"batch_id": upper.lower()}}]


def test_claim_moves_matched_to_notifying_once(conn: Any, matched_batch: uuid.UUID) -> None:
    assert claim(conn, matched_batch)["claimed"] == 1
    assert batch_status(conn, matched_batch) == "notifying"
    assert claim(conn, matched_batch)["claimed"] == 0
    assert batch_status(conn, matched_batch) == "notifying"


@pytest.mark.parametrize("status", ["processed", "matching", "notified", "failed", "loading"])
def test_claim_refuses_a_batch_that_is_not_matched(conn: Any, status: str) -> None:
    batch_id = new_batch(conn, status)
    assert claim(conn, batch_id)["claimed"] == 0
    assert batch_status(conn, batch_id) == status


def test_claim_of_an_unknown_batch_claims_nothing(conn: Any) -> None:
    assert claim(conn, uuid.uuid4())["claimed"] == 0


def test_select_groups_offers_per_user_cheapest_first(conn: Any, matched_batch: uuid.UUID) -> None:
    ids = two_users_three_offers(conn, matched_batch)
    selected = select_recipients(conn, matched_batch)
    assert selected["users_waiting"] == 2
    assert selected["users_selected"] == 2
    first, second = selected["recipients"]
    assert (first["user_id"], second["user_id"]) == (str(FIRST_USER), str(SECOND_USER))
    assert first["name"] == "Asha Rao"
    assert first["original_email"] == "asha@example.invalid"
    assert [o["product_id"] for o in first["offers"]] == [ids["cheap"], ids["dear"]]
    assert [o["product_id"] for o in second["offers"]] == [ids["other"]]
    assert first["offers"][0] == {
        "product_id": ids["cheap"],
        "lender": "test",
        "product_name": "Cheap Loan",
        "rate_min": 10.5,
        "rate_max": 14,
        "source_url": "https://bank.example/cheap",
        "stage": "rules",
        "reason": "meets every published criterion",
    }


def test_select_returns_one_empty_row_when_nothing_is_waiting(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    selected = select_recipients(conn, matched_batch)
    assert selected["recipients"] == []
    assert selected["users_waiting"] == 0
    assert selected["users_selected"] == 0
    assert selected["batch_id"] == str(matched_batch)


def test_select_skips_notified_inactive_and_other_batch_matches(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    live = add_product(conn, "Live", interest_rate_min=10, interest_rate_max=11)
    retired = add_product(conn, "Retired", active=False, interest_rate_min=9, interest_rate_max=9)
    already = add_product(conn, "Already", interest_rate_min=8, interest_rate_max=8)
    other_batch = new_batch(conn, "matched")
    add_user_with_id(conn, matched_batch, FIRST_USER, "Asha Rao", "asha@example.invalid")
    add_user_with_id(conn, matched_batch, SECOND_USER, "Ben Roy", "ben@example.invalid")
    add_user_with_id(conn, other_batch, THIRD_USER, "Cy Dan", "cy@example.invalid")
    add_match(conn, matched_batch, FIRST_USER, live)
    add_match(conn, matched_batch, FIRST_USER, retired)
    add_match(conn, matched_batch, FIRST_USER, already, notified=True)
    add_match(conn, matched_batch, SECOND_USER, retired)
    add_match(conn, other_batch, THIRD_USER, live)
    selected = select_recipients(conn, matched_batch)
    assert [r["user_id"] for r in selected["recipients"]] == [str(FIRST_USER)]
    assert [o["product_id"] for o in selected["recipients"][0]["offers"]] == [live]
    assert selected["users_waiting"] == 1


def test_select_caps_users_but_counts_everyone_waiting(conn: Any, matched_batch: uuid.UUID) -> None:
    product = add_product(conn, "Only", interest_rate_min=10, interest_rate_max=11)
    users = [FIRST_USER, SECOND_USER, THIRD_USER, FOURTH_USER]
    for index, user in enumerate(users):
        add_user_with_id(conn, matched_batch, user, f"User {index}", f"u{index}@example.invalid")
        add_match(conn, matched_batch, user, product)
    selected = select_recipients(conn, matched_batch, max_emails=2)
    assert [r["user_id"] for r in selected["recipients"]] == [str(u) for u in users[:2]]
    assert selected["users_selected"] == 2
    assert selected["users_waiting"] == 4


def test_build_redirects_every_user_to_a_test_inbox_deterministically(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    product = add_product(conn, "Only", interest_rate_min=10, interest_rate_max=11)
    users = [FIRST_USER, SECOND_USER, THIRD_USER, FOURTH_USER]
    for index, user in enumerate(users):
        add_user_with_id(conn, matched_batch, user, f"User {index}", f"u{index}@example.invalid")
        add_match(conn, matched_batch, user, product)
    selected = select_recipients(conn, matched_batch, max_emails=4)
    first = build_emails(conn, matched_batch, selected)
    again = build_emails(conn, matched_batch, selected)
    assert [e["to"] for e in first["emails"]] == [e["to"] for e in again["emails"]]
    assert [e["to"] for e in first["emails"]] == [ALIASES[0], ALIASES[1], ALIASES[2], ALIASES[0]]
    assert all(e["to"] != e["original_email"] for e in first["emails"])
    assert first["dry_run"] is True


def test_build_writes_subject_text_and_html_for_one_user(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    two_users_three_offers(conn, matched_batch)
    built = build_emails(conn, matched_batch, select_recipients(conn, matched_batch))
    asha, ben = built["emails"]
    assert asha["subject"] == "[TEST] 2 personal loan options you may qualify for"
    assert ben["subject"] == "[TEST] 1 personal loan option you may qualify for"
    assert asha["offer_count"] == 2
    assert "Hello Asha Rao," in asha["text"]
    assert "1. test - Cheap Loan\n   Interest rate 10.5% to 14% p.a." in asha["text"]
    assert "Details: https://bank.example/cheap" in asha["text"]
    assert "2. test - Dear Loan\n   Interest rate 12% p.a." in asha["text"]
    assert "Intended for: Asha Rao <asha@example.invalid>" in asha["text"]
    assert "indicative only" in asha["text"]
    assert "redirected to a test inbox" in asha["text"]
    assert "<strong>test - Cheap Loan</strong>" in asha["html"]
    assert '<a href="https://bank.example/cheap">Lender page</a>' in asha["html"]
    assert "Intended for: Asha Rao &lt;asha@example.invalid&gt;" in asha["html"]
    assert asha["html"].count("asha@example.invalid") == 1
    assert asha["text"].count("asha@example.invalid") == 1


@pytest.mark.parametrize(
    ("rate_min", "rate_max", "expected"),
    [
        (10.5, 14, "Interest rate 10.5% to 14% p.a."),
        (12, 12, "Interest rate 12% p.a."),
        (11, None, "Interest rate from 11% p.a."),
        (None, 18, "Interest rate up to 18% p.a."),
        (None, None, "Interest rate not published on the lender page"),
    ],
)
def test_build_describes_every_published_rate_shape(
    conn: Any, matched_batch: uuid.UUID, rate_min: Any, rate_max: Any, expected: str
) -> None:
    product = add_product(conn, "Shape", interest_rate_min=rate_min, interest_rate_max=rate_max)
    add_user_with_id(conn, matched_batch, FIRST_USER, "Asha Rao", "asha@example.invalid")
    add_match(conn, matched_batch, FIRST_USER, product)
    built = build_emails(conn, matched_batch, select_recipients(conn, matched_batch))
    assert expected in built["emails"][0]["text"]
    assert expected in built["emails"][0]["html"]


def test_build_escapes_hostile_values_in_html_and_refuses_script_links(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    product = add_product(
        conn,
        "<script>alert(1)</script>",
        interest_rate_min=10,
        interest_rate_max=11,
        source_url="javascript:alert(1)",
    )
    add_user_with_id(conn, matched_batch, FIRST_USER, '"><img src=x onerror=alert(1)>', "a@b.co")
    add_match(conn, matched_batch, FIRST_USER, product, reason='<b>bold</b> & "quoted"')
    html = build_emails(conn, matched_batch, select_recipients(conn, matched_batch))["emails"][0][
        "html"
    ]
    assert "<script>" not in html
    assert "<img" not in html
    assert "<b>bold</b>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&quot;&gt;&lt;img src=x onerror=alert(1)&gt;" in html
    assert "&lt;b&gt;bold&lt;/b&gt; &amp; &quot;quoted&quot;" in html
    assert "javascript:" not in html
    assert "<a href" not in html


def test_build_shortens_a_long_reason(conn: Any, matched_batch: uuid.UUID) -> None:
    product = add_product(conn, "Wordy", interest_rate_min=10, interest_rate_max=11)
    add_user_with_id(conn, matched_batch, FIRST_USER, "Asha Rao", "asha@example.invalid")
    add_match(conn, matched_batch, FIRST_USER, product, reason="word " * 200)
    text = build_emails(conn, matched_batch, select_recipients(conn, matched_batch))["emails"][0][
        "text"
    ]
    why = next(line for line in text.splitlines() if line.strip().startswith("Why:"))
    assert len(why.strip()) <= len("Why: ") + 240
    assert why.endswith("…")


def test_build_with_no_recipients_yields_one_item_with_no_emails(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    built = build_emails(conn, matched_batch, select_recipients(conn, matched_batch))
    assert built["emails"] == []
    assert built["users_waiting"] == 0


def test_guard_passes_a_clean_run_and_reports_what_it_checked(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    two_users_three_offers(conn, matched_batch)
    built = build_emails(conn, matched_batch, select_recipients(conn, matched_batch))
    guarded = guard(conn, matched_batch, built)
    assert guarded["guard"] == {"checked": 2, "test_inboxes": 3}
    assert guarded["emails"] == built["emails"]


def test_guard_passes_an_empty_run(conn: Any, matched_batch: uuid.UUID) -> None:
    built = build_emails(conn, matched_batch, select_recipients(conn, matched_batch))
    assert guard(conn, matched_batch, built)["guard"]["checked"] == 0


def tampered(
    conn: Any, batch_id: uuid.UUID, change: Callable[[dict[str, Any]], None]
) -> dict[str, Any]:
    two_users_three_offers(conn, batch_id)
    built = build_emails(conn, batch_id, select_recipients(conn, batch_id))
    change(built["emails"][1])
    return built


@pytest.mark.parametrize(
    "bad_address",
    [
        "asha@example.invalid",
        "someone.else@gmail.com",
        "MRRSSONI12@GMAIL.COM",
        "mrrssoni12@gmail.com,real.person@example.com",
        "mrrssoni12@gmail.com ",
        "mrrssoni12+three@gmail.com",
        "",
        None,
        ["mrrssoni12@gmail.com"],
    ],
)
def test_guard_blocks_any_recipient_that_is_not_exactly_a_test_inbox(
    conn: Any, matched_batch: uuid.UUID, bad_address: Any
) -> None:
    built = tampered(conn, matched_batch, lambda email: email.update(to=bad_address))
    with pytest.raises(subprocess.CalledProcessError) as raised:
        guard(conn, matched_batch, built)
    assert "recipient guard blocked the run (1 problems)" in raised.value.stderr
    assert str(SECOND_USER) in raised.value.stderr
    assert "not a test inbox" in raised.value.stderr


@pytest.mark.parametrize("field", ["cc", "bcc", "replyTo"])
def test_guard_blocks_copy_and_reply_to_recipients(
    conn: Any, matched_batch: uuid.UUID, field: str
) -> None:
    built = tampered(conn, matched_batch, lambda email: email.update({field: ALIASES[0]}))
    with pytest.raises(subprocess.CalledProcessError) as raised:
        guard(conn, matched_batch, built)
    assert "copy or reply-to recipient" in raised.value.stderr


def test_guard_blocks_more_emails_than_the_cap(conn: Any, matched_batch: uuid.UUID) -> None:
    two_users_three_offers(conn, matched_batch)
    built = build_emails(conn, matched_batch, select_recipients(conn, matched_batch))
    config = validated_config(conn, matched_batch)
    with pytest.raises(subprocess.CalledProcessError) as raised:
        guard(conn, matched_batch, built, {**config, "max_emails": 1})
    assert "2 emails exceed the cap of 1" in raised.value.stderr


def test_guard_trusts_the_config_node_and_not_the_composed_item(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    two_users_three_offers(conn, matched_batch)
    built = build_emails(conn, matched_batch, select_recipients(conn, matched_batch))
    built["aliases"] = [e["to"] for e in built["emails"]]
    config = validated_config(conn, matched_batch)
    with pytest.raises(subprocess.CalledProcessError) as raised:
        guard(conn, matched_batch, built, {**config, "aliases": ["elsewhere@example.com"]})
    assert "not a test inbox" in raised.value.stderr


def test_guard_with_an_empty_inbox_list_blocks_everything(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    two_users_three_offers(conn, matched_batch)
    built = build_emails(conn, matched_batch, select_recipients(conn, matched_batch))
    config = validated_config(conn, matched_batch)
    with pytest.raises(subprocess.CalledProcessError) as raised:
        guard(conn, matched_batch, built, {**config, "aliases": []})
    assert "the test inbox list is empty" in raised.value.stderr


def test_guard_reports_the_count_but_only_the_first_five_problems(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    built = {
        "emails": [{"user_id": f"u{i}", "to": f"x{i}@example.com"} for i in range(8)],
        "users_waiting": 8,
        "dry_run": True,
    }
    with pytest.raises(subprocess.CalledProcessError) as raised:
        guard(
            conn, matched_batch, built, {**validated_config(conn, matched_batch), "max_emails": 9}
        )
    assert "(8 problems)" in raised.value.stderr
    assert "u4 " in raised.value.stderr
    assert "u5 " not in raised.value.stderr


def test_release_returns_the_batch_to_matched_and_reports_counts(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    two_users_three_offers(conn, matched_batch)
    result = run_chain(conn, matched_batch)
    assert result["released"] == {
        "batch_id": str(matched_batch),
        "released": 1,
        "emails_composed": 2,
        "users_waiting": 2,
        "dry_run": True,
        "emails_sent": 0,
    }
    assert batch_status(conn, matched_batch) == "matched"


def test_release_does_nothing_for_a_batch_that_is_not_notifying(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    rows = conn.run(
        node_sql(RELEASE_NODE, RELEASE_PARAMS),
        batch_id=matched_batch,
        composed=0,
        waiting=0,
        dry_run=True,
    )
    assert single_row(conn, rows)["released"] == 0
    assert batch_status(conn, matched_batch) == "matched"


def test_full_chain_marks_nothing_and_a_second_run_composes_the_same_emails(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    two_users_three_offers(conn, matched_batch)
    first = run_chain(conn, matched_batch)
    second = run_chain(conn, matched_batch)
    assert unnotified(conn, matched_batch) == 3
    assert first["emails"] == second["emails"]
    assert len(first["emails"]) == 2
    assert batch_status(conn, matched_batch) == "matched"


def test_full_chain_with_nothing_waiting_still_releases_the_batch(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    result = run_chain(conn, matched_batch)
    assert result["emails"] == []
    assert result["released"]["released"] == 1
    assert batch_status(conn, matched_batch) == "matched"


def test_failure_branch_marks_a_notifying_batch_failed_with_the_message(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    claim(conn, matched_batch)
    rows = conn.run(node_sql(FAIL_NODE, FAIL_PARAMS), batch_id=matched_batch, message="x" * 2000)
    row = single_row(conn, rows)
    assert row["marked"] == 1
    assert len(row["error"]) == 1000
    status, error = conn.run(
        "SELECT status, error FROM upload_batches WHERE id = :id", id=matched_batch
    )[0]
    assert status == "failed"
    assert error.startswith("notification failed: xxx")


def test_failure_branch_leaves_a_batch_that_is_not_notifying_alone(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    rows = conn.run(node_sql(FAIL_NODE, FAIL_PARAMS), batch_id=matched_batch, message="boom")
    row = single_row(conn, rows)
    assert row["marked"] == 0
    assert row["error"] == "boom"
    assert batch_status(conn, matched_batch) == "matched"


def test_select_ignores_a_user_whose_matches_are_all_notified_even_under_a_cap(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    product = add_product(conn, "Only", interest_rate_min=10, interest_rate_max=11)
    add_user_with_id(conn, matched_batch, FIRST_USER, "Done User", "done@example.invalid")
    add_user_with_id(conn, matched_batch, SECOND_USER, "Waiting User", "waiting@example.invalid")
    add_match(conn, matched_batch, FIRST_USER, product, notified=True)
    add_match(conn, matched_batch, SECOND_USER, product)
    selected = select_recipients(conn, matched_batch, max_emails=1)
    assert [r["user_id"] for r in selected["recipients"]] == [str(SECOND_USER)]
    assert selected["users_waiting"] == 1
