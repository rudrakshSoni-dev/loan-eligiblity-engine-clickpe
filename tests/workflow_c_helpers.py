"""Workflow C's exported SQL and Code nodes as callables, shared by its compose and send tests.

Each helper runs one node exactly as exported and returns what n8n would pass to the next node, so
the tests can chain them the way the workflow does.
"""

import json
import uuid
from pathlib import Path
from typing import Any

from tests.workflow_b_helpers import add_product, node_query, run_code_node, single_row

WORKFLOW_C = (
    Path(__file__).resolve().parents[1] / "n8n" / "workflows" / "workflow-c-notification.json"
)
WORKFLOW_C_ID = "wfcnotification01"

READ_BATCH_NODE = "Check · Read batch_id"
CONFIG_LOAD_NODE = "Config · Load settings"
CONFIG_VALIDATE_NODE = "Config · Validate settings"
CLAIM_NODE = "Claim · matched to notifying"
SELECT_NODE = "Compose · Select recipients"
BUILD_NODE = "Compose · Build emails"
GUARD_NODE = "Guard · Recipients are test inboxes"
RELEASE_NODE = "Release · notifying back to matched"
FAIL_NODE = "Fail · Mark batch failed (Notify)"
DRY_RUN_NODE = "Send · Dry run?"
ANYTHING_NODE = "Send · Anything to send?"
SPLIT_NODE = "Send · One item per email"
LOOP_NODE = "Send · Loop emails (one at a time)"
SES_NODE = "Send · SES email"
MARK_NODE = "Send · Mark notified"
PACE_NODE = "Send · Pace 1 s (SES sandbox rate)"
FINISH_NODE = "Finish · notifying to notified"

BATCH_PARAMS = {"$1": ":batch_id"}
SELECT_PARAMS = {"$1": ":batch_id", "$2": ":max_emails"}
RELEASE_PARAMS = {"$1": ":batch_id", "$2": ":composed", "$3": ":waiting", "$4": ":dry_run"}
FAIL_PARAMS = {"$1": ":batch_id", "$2": ":message"}
MARK_PARAMS = {"$1": ":batch_id", "$2": ":user_id", "$3": ":product_ids", "$4": ":message_id"}
FINISH_PARAMS = {"$1": ":batch_id", "$2": ":claimed_at"}

ALIASES = ["mrrssoni12@gmail.com", "mrrssoni12+one@gmail.com", "mrrssoni12+two@gmail.com"]
FROM_ADDRESS = "mrrssoni12@gmail.com"
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


def split_emails(guarded: dict[str, Any]) -> list[dict[str, Any]]:
    return [item["json"] for item in code(SPLIT_NODE, guarded)]


def mark_notified(
    conn: Any, email: dict[str, Any], message_id: str = "ses-message-1"
) -> dict[str, Any]:
    rows = conn.run(
        node_sql(MARK_NODE, MARK_PARAMS),
        batch_id=email["batch_id"],
        user_id=email["user_id"],
        product_ids=json.dumps(email["product_ids"]),
        message_id=message_id,
    )
    return single_row(conn, rows)


def finish(conn: Any, batch_id: uuid.UUID, claimed_at: str) -> dict[str, Any]:
    rows = conn.run(node_sql(FINISH_NODE, FINISH_PARAMS), batch_id=batch_id, claimed_at=claimed_at)
    return single_row(conn, rows)


def send_chain(conn: Any, batch_id: uuid.UUID, max_emails: int = 5) -> dict[str, Any]:
    claimed = claim(conn, batch_id)
    assert claimed["claimed"] == 1
    selected = select_recipients(conn, batch_id, max_emails)
    guarded = guard(conn, batch_id, build_emails(conn, batch_id, selected))
    marks = [mark_notified(conn, email) for email in split_emails(guarded)]
    return {**guarded, "marks": marks, "finished": finish(conn, batch_id, claimed["claimed_at"])}


def batch_status(conn: Any, batch_id: uuid.UUID) -> str:
    return str(conn.run("SELECT status FROM upload_batches WHERE id = :id", id=batch_id)[0][0])


def unnotified(conn: Any, batch_id: uuid.UUID) -> int:
    rows = conn.run(
        "SELECT count(*) FROM matches WHERE batch_id = :id AND notified_at IS NULL", id=batch_id
    )
    return int(rows[0][0])


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
