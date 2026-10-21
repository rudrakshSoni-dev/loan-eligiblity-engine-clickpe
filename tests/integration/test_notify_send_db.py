"""Workflow C sending half on real PostgreSQL 16: split, mark notified and finish, as exported.

SES itself is not called here; each test stands in for a successful send by running the mark step
for that email, which is what the workflow does after SES answers. The wiring that puts SES between
the split and the mark, and the guard in front of all of it, is checked in the wiring tests.
"""

import os
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest

from tests.workflow_b_helpers import NODE_BINARY, add_product, new_batch
from tests.workflow_c_helpers import (
    FAIL_NODE,
    FAIL_PARAMS,
    FIRST_USER,
    SECOND_USER,
    THIRD_USER,
    add_match,
    add_user_with_id,
    batch_status,
    build_emails,
    claim,
    finish,
    guard,
    mark_notified,
    node_sql,
    select_recipients,
    send_chain,
    split_emails,
    two_users_three_offers,
    unnotified,
)

pytestmark = [
    pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set"),
    pytest.mark.skipif(NODE_BINARY is None, reason="node not installed"),
]


@pytest.fixture
def conn(connect_db: Callable[[], Any]) -> Any:
    return connect_db()


@pytest.fixture
def matched_batch(conn: Any) -> uuid.UUID:
    return new_batch(conn, "matched")


def guarded_run(conn: Any, batch_id: uuid.UUID, max_emails: int = 5) -> dict[str, Any]:
    selected = select_recipients(conn, batch_id, max_emails)
    return guard(conn, batch_id, build_emails(conn, batch_id, selected))


def notified_pairs(conn: Any, batch_id: uuid.UUID) -> set[tuple[str, int]]:
    rows = conn.run(
        "SELECT user_id::text, product_id FROM matches"
        " WHERE batch_id = :id AND notified_at IS NOT NULL",
        id=batch_id,
    )
    return {(str(user), int(product)) for user, product in rows}


def test_claim_returns_a_claim_time_that_precedes_every_mark(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    two_users_three_offers(conn, matched_batch)
    claimed = claim(conn, matched_batch)
    emails = split_emails(guarded_run(conn, matched_batch))
    mark_notified(conn, emails[0])
    claimed_at = conn.run("SELECT CAST(:t AS timestamptz)", t=claimed["claimed_at"])[0][0]
    marked_at = conn.run(
        "SELECT min(notified_at) FROM matches WHERE batch_id = :id", id=matched_batch
    )[0][0]
    assert isinstance(claimed_at, datetime)
    assert claimed_at <= marked_at


def test_split_gives_one_item_per_email_carrying_the_batch_and_everything_ses_needs(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    two_users_three_offers(conn, matched_batch)
    guarded = guarded_run(conn, matched_batch)
    items = split_emails(guarded)
    assert len(items) == 2
    for item, email in zip(items, guarded["emails"], strict=True):
        assert item == {"batch_id": str(matched_batch), **email}
        assert {"to", "subject", "html", "user_id", "product_ids"} <= set(item)


def test_split_of_an_empty_run_gives_no_items(conn: Any, matched_batch: uuid.UUID) -> None:
    assert split_emails(guarded_run(conn, matched_batch)) == []


def test_mark_sets_exactly_the_products_in_that_email_for_that_user(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    products = two_users_three_offers(conn, matched_batch)
    asha = split_emails(guarded_run(conn, matched_batch))[0]
    late = add_product(conn, "Matched after compose", interest_rate_min=9, interest_rate_max=9)
    add_match(conn, matched_batch, FIRST_USER, late)
    other_batch = new_batch(conn, "matched")
    add_user_with_id(conn, other_batch, THIRD_USER, "Other Batch", "other@example.invalid")
    add_match(conn, other_batch, THIRD_USER, products["cheap"])
    result = mark_notified(conn, asha, message_id="0108abc-ses")
    assert result == {
        "user_id": str(FIRST_USER),
        "ses_message_id": "0108abc-ses",
        "matches_marked": 2,
    }
    assert notified_pairs(conn, matched_batch) == {
        (str(FIRST_USER), products["cheap"]),
        (str(FIRST_USER), products["dear"]),
    }
    assert unnotified(conn, matched_batch) == 2
    assert unnotified(conn, other_batch) == 1


def test_mark_twice_changes_nothing_so_a_retry_is_safe(conn: Any, matched_batch: uuid.UUID) -> None:
    two_users_three_offers(conn, matched_batch)
    asha = split_emails(guarded_run(conn, matched_batch))[0]
    assert mark_notified(conn, asha)["matches_marked"] == 2
    first = conn.run("SELECT array_agg(notified_at ORDER BY product_id) FROM matches")[0][0]
    conn.run("SELECT pg_sleep(0.01)")
    assert mark_notified(conn, asha)["matches_marked"] == 0
    again = conn.run("SELECT array_agg(notified_at ORDER BY product_id) FROM matches")[0][0]
    assert first == again


def test_mark_without_a_message_id_records_null(conn: Any, matched_batch: uuid.UUID) -> None:
    two_users_three_offers(conn, matched_batch)
    asha = split_emails(guarded_run(conn, matched_batch))[0]
    assert mark_notified(conn, asha, message_id="")["ses_message_id"] is None


def test_mark_ignores_product_ids_that_are_not_this_users_matches(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    products = two_users_three_offers(conn, matched_batch)
    asha = split_emails(guarded_run(conn, matched_batch))[0]
    forged = {**asha, "product_ids": [products["other"]]}
    assert mark_notified(conn, forged)["matches_marked"] == 0
    assert unnotified(conn, matched_batch) == 3


def test_finish_marks_the_batch_notified_and_reads_the_counts_back(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    product = add_product(conn, "Only", interest_rate_min=10, interest_rate_max=11)
    for index, user in enumerate((FIRST_USER, SECOND_USER, THIRD_USER)):
        add_user_with_id(conn, matched_batch, user, f"User {index}", f"u{index}@example.invalid")
        add_match(conn, matched_batch, user, product)
    result = send_chain(conn, matched_batch, max_emails=2)
    assert [m["matches_marked"] for m in result["marks"]] == [1, 1]
    assert result["finished"] == {
        "batch_id": str(matched_batch),
        "finished": 1,
        "dry_run": False,
        "emails_sent": 2,
        "matches_notified": 2,
        "users_still_waiting": 1,
    }
    assert batch_status(conn, matched_batch) == "notified"


def test_finish_counts_only_what_this_run_notified(conn: Any, matched_batch: uuid.UUID) -> None:
    product = add_product(conn, "Only", interest_rate_min=10, interest_rate_max=11)
    add_user_with_id(conn, matched_batch, FIRST_USER, "Earlier", "earlier@example.invalid")
    add_user_with_id(conn, matched_batch, SECOND_USER, "Now", "now@example.invalid")
    add_match(conn, matched_batch, FIRST_USER, product)
    add_match(conn, matched_batch, SECOND_USER, product)
    conn.run(
        "UPDATE matches SET notified_at = now() - interval '1 hour' WHERE user_id = :u",
        u=FIRST_USER,
    )
    finished = send_chain(conn, matched_batch)["finished"]
    assert finished["emails_sent"] == 1
    assert finished["users_still_waiting"] == 0


def test_finish_with_nothing_to_send_still_closes_the_batch(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    result = send_chain(conn, matched_batch)
    assert result["marks"] == []
    assert result["finished"]["finished"] == 1
    assert result["finished"]["emails_sent"] == 0
    assert result["finished"]["users_still_waiting"] == 0
    assert batch_status(conn, matched_batch) == "notified"


def test_finish_leaves_a_batch_that_is_not_notifying_alone(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    claimed_at = conn.run("SELECT now()::text")[0][0]
    assert finish(conn, matched_batch, claimed_at)["finished"] == 0
    assert batch_status(conn, matched_batch) == "matched"


def test_finish_does_not_count_inactive_products_as_waiting(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    retired = add_product(conn, "Retired", active=False, interest_rate_min=10)
    add_user_with_id(conn, matched_batch, FIRST_USER, "Asha Rao", "asha@example.invalid")
    add_match(conn, matched_batch, FIRST_USER, retired)
    finished = send_chain(conn, matched_batch)["finished"]
    assert finished["users_still_waiting"] == 0
    assert unnotified(conn, matched_batch) == 1


def test_a_finished_batch_is_not_claimed_again(conn: Any, matched_batch: uuid.UUID) -> None:
    two_users_three_offers(conn, matched_batch)
    send_chain(conn, matched_batch)
    assert claim(conn, matched_batch)["claimed"] == 0
    assert batch_status(conn, matched_batch) == "notified"


def test_a_rerun_after_a_full_send_emails_nobody(conn: Any, matched_batch: uuid.UUID) -> None:
    two_users_three_offers(conn, matched_batch)
    first = send_chain(conn, matched_batch)
    conn.run("UPDATE upload_batches SET status = 'matched' WHERE id = :id", id=matched_batch)
    second = send_chain(conn, matched_batch)
    assert len(first["marks"]) == 2
    assert second["emails"] == []
    assert second["marks"] == []
    assert second["finished"]["emails_sent"] == 0
    assert unnotified(conn, matched_batch) == 0


def test_a_capped_send_leaves_the_rest_for_the_next_run(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    product = add_product(conn, "Only", interest_rate_min=10, interest_rate_max=11)
    users = (FIRST_USER, SECOND_USER, THIRD_USER)
    for index, user in enumerate(users):
        add_user_with_id(conn, matched_batch, user, f"User {index}", f"u{index}@example.invalid")
        add_match(conn, matched_batch, user, product)
    first = send_chain(conn, matched_batch, max_emails=2)
    conn.run("UPDATE upload_batches SET status = 'matched' WHERE id = :id", id=matched_batch)
    second = send_chain(conn, matched_batch, max_emails=2)
    assert [e["user_id"] for e in first["emails"]] == [str(FIRST_USER), str(SECOND_USER)]
    assert [e["user_id"] for e in second["emails"]] == [str(THIRD_USER)]
    assert second["finished"]["users_still_waiting"] == 0


def test_a_failure_mid_loop_keeps_what_was_sent_and_the_rerun_sends_only_the_rest(
    conn: Any, matched_batch: uuid.UUID
) -> None:
    two_users_three_offers(conn, matched_batch)
    assert claim(conn, matched_batch)["claimed"] == 1
    asha, ben = split_emails(guarded_run(conn, matched_batch))
    mark_notified(conn, asha)
    conn.run(
        node_sql(FAIL_NODE, FAIL_PARAMS),
        batch_id=matched_batch,
        message="Throttling: Maximum sending rate exceeded.",
    )
    assert batch_status(conn, matched_batch) == "failed"
    assert unnotified(conn, matched_batch) == 1
    conn.run("UPDATE upload_batches SET status = 'matched' WHERE id = :id", id=matched_batch)
    rerun = send_chain(conn, matched_batch)
    assert [e["user_id"] for e in rerun["emails"]] == [ben["user_id"]]
    assert rerun["finished"]["emails_sent"] == 1
    assert unnotified(conn, matched_batch) == 0
