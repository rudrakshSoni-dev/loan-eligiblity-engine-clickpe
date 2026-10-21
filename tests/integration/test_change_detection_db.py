"""Workflow A's change detection on PostgreSQL 16: the lookup and the unchanged-page update."""

import hashlib
import os
from collections.abc import Callable
from typing import Any

import pytest

from tests.workflow_b_helpers import node_query, single_row
from tests.workflow_gateway_helpers import WORKFLOWS_DIR

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DB_HOST"), reason="TEST_DB_HOST not set")

WORKFLOW_A = WORKFLOWS_DIR / "workflow-a-product-discovery.json"
LOOKUP_NODE = "Lookup · Stored content hash"
TOUCH_NODE = "Touch · last_seen_at + crawl_runs (unchanged)"
PARAMS = {"$1": ":source", "$2": ":product_name", "$3": ":criteria_text"}
SOURCE = "ICICI Bank"
PRODUCT = "Personal Loan"
TEXT = "Minimum net monthly income of ₹30,000\nAge between 21 and 60 years"
EDITED_TEXT = "Minimum net monthly income of ₹35,000\nAge between 21 and 60 years"


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def conn(connect_db: Callable[[], Any]) -> Any:
    return connect_db()


def add_crawled(
    conn: Any, text: str = TEXT, active: bool = True, is_seed: bool = False, source: str = SOURCE
) -> int:
    rows = conn.run(
        "INSERT INTO loan_products (source, product_name, content_hash, active, is_seed,"
        " last_seen_at) VALUES (:source, :name, :hash, :active, :is_seed,"
        " now() - interval '3 days') RETURNING id",
        source=source,
        name=PRODUCT,
        hash=sha256_hex(text),
        active=active,
        is_seed=is_seed,
    )
    return int(rows[0][0])


def lookup(conn: Any, text: str) -> bool:
    query = node_query(LOOKUP_NODE, PARAMS, WORKFLOW_A)
    row = single_row(conn, conn.run(query, source=SOURCE, product_name=PRODUCT, criteria_text=text))
    return bool(row["unchanged"])


def touch(conn: Any, text: str) -> list[dict[str, Any]]:
    query = node_query(TOUCH_NODE, PARAMS, WORKFLOW_A)
    rows = conn.run(query, source=SOURCE, product_name=PRODUCT, criteria_text=text)
    names = [c["name"] for c in conn.columns]
    return [dict(zip(names, row, strict=True)) for row in rows]


def product(conn: Any, product_id: int) -> dict[str, Any]:
    rows = conn.run(
        "SELECT active, last_seen_at > now() - interval '1 minute' AS seen_now, content_hash"
        " FROM loan_products WHERE id = :id",
        id=product_id,
    )
    return single_row(conn, rows)


def crawl_rows(conn: Any) -> list[tuple[Any, ...]]:
    rows = conn.run("SELECT source, status, products_found, changed, llm_calls FROM crawl_runs")
    return [tuple(row) for row in rows]


def test_lookup_says_unchanged_when_the_stored_hash_equals_the_texts_sha256(conn: Any) -> None:
    add_crawled(conn)
    assert lookup(conn, TEXT) is True


def test_lookup_says_changed_when_one_character_of_the_text_differs(conn: Any) -> None:
    add_crawled(conn)
    assert lookup(conn, EDITED_TEXT) is False


def test_lookup_says_changed_for_a_source_never_stored(conn: Any) -> None:
    assert lookup(conn, TEXT) is False


def test_lookup_ignores_a_seed_row_with_the_same_key_and_text(conn: Any) -> None:
    add_crawled(conn, is_seed=True)
    assert lookup(conn, TEXT) is False


def test_lookup_always_returns_exactly_one_row(conn: Any) -> None:
    query = node_query(LOOKUP_NODE, PARAMS, WORKFLOW_A)
    rows = conn.run(query, source="Nobody", product_name=PRODUCT, criteria_text=TEXT)
    assert len(rows) == 1


def test_touch_bumps_last_seen_and_logs_one_unchanged_run_without_an_llm_call(conn: Any) -> None:
    product_id = add_crawled(conn)
    assert product(conn, product_id)["seen_now"] is False

    out = touch(conn, TEXT)

    assert len(out) == 1
    assert out[0]["product_id"] == product_id
    assert (out[0]["reactivated"], out[0]["changed"], out[0]["llm_calls"]) == (False, False, 0)
    assert product(conn, product_id)["seen_now"] is True
    assert crawl_rows(conn) == [(SOURCE, "ok", 1, False, 0)]
    assert out[0]["crawl_run_id"] is not None


def test_touch_reactivates_a_retired_product_with_unchanged_text(conn: Any) -> None:
    product_id = add_crawled(conn, active=False)

    out = touch(conn, TEXT)

    assert out[0]["reactivated"] is True
    assert product(conn, product_id)["active"] is True


def test_touch_does_nothing_and_logs_nothing_when_the_text_changed(conn: Any) -> None:
    product_id = add_crawled(conn)

    assert touch(conn, EDITED_TEXT) == []

    assert product(conn, product_id)["seen_now"] is False
    assert product(conn, product_id)["content_hash"] == sha256_hex(TEXT)
    assert crawl_rows(conn) == []


def test_touch_never_updates_a_seed_row(conn: Any) -> None:
    product_id = add_crawled(conn, is_seed=True)

    assert touch(conn, TEXT) == []

    assert product(conn, product_id)["seen_now"] is False


def test_touch_only_updates_the_matching_source(conn: Any) -> None:
    other_id = add_crawled(conn, source="HDFC Bank")
    add_crawled(conn)

    touch(conn, TEXT)

    assert product(conn, other_id)["seen_now"] is False


def test_touching_twice_logs_two_runs_and_keeps_one_product(conn: Any) -> None:
    add_crawled(conn)

    touch(conn, TEXT)
    touch(conn, TEXT)

    assert len(crawl_rows(conn)) == 2
    assert conn.run("SELECT count(*) FROM loan_products")[0][0] == 1
