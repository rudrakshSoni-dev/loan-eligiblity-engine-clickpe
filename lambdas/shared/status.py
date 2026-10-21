"""Read-only batch progress for the UI poller: counters, first rejects, match counts, funnel.

Four small queries on indexed columns, run in autocommit. `pipeline_runs` counters are NULL until
their stage has run, and they are passed through as null so the UI can tell "not measured yet"
from a measured zero. When a batch has been matched more than once, the latest run is shown.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from lambdas.shared.db import Connection

REJECT_PREVIEW_LIMIT = 5

BATCH_SQL = (
    "SELECT status, error, total_chunks, chunks_done, rows_ok, rows_rejected,"
    " created_at, updated_at FROM upload_batches WHERE id = :id"
)
REJECTS_SQL = (
    "SELECT line_no, reason FROM rejected_rows WHERE batch_id = :id ORDER BY line_no LIMIT :limit"
)
MATCHES_SQL = "SELECT count(*), count(notified_at) FROM matches WHERE batch_id = :id"
FUNNEL_COLUMNS = (
    "total_pairs",
    "stage1_pairs",
    "stage1_near_miss",
    "stage2_clear",
    "stage2_borderline",
    "stage2_reject",
    "llm_cohorts",
    "cache_hits",
    "llm_calls",
    "llm_tokens",
    "stage3_eligible",
    "stage3_not_eligible",
    "unresolved_budget",
    "unresolved_error",
    "final_matches",
    "stage_ms",
    "started_at",
    "finished_at",
)
FUNNEL_SQL = (
    f"SELECT {', '.join(FUNNEL_COLUMNS)}"
    " FROM pipeline_runs WHERE batch_id = :id ORDER BY id DESC LIMIT 1"
)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def funnel(conn: Connection, batch_id: uuid.UUID) -> dict[str, Any] | None:
    rows = conn.run(FUNNEL_SQL, id=batch_id)
    if not rows:
        return None
    values = dict(zip(FUNNEL_COLUMNS, rows[0], strict=True))
    values["started_at"] = iso(values["started_at"])
    values["finished_at"] = iso(values["finished_at"])
    return values


def batch_status(conn: Connection, batch_id: uuid.UUID) -> dict[str, Any] | None:
    """Return the progress document for a batch, or None if the batch does not exist."""
    rows = conn.run(BATCH_SQL, id=batch_id)
    if not rows:
        return None
    status, error, total, done, ok, rejected, created, updated = rows[0]
    rejects = conn.run(REJECTS_SQL, id=batch_id, limit=REJECT_PREVIEW_LIMIT)
    matches, notified = conn.run(MATCHES_SQL, id=batch_id)[0]
    return {
        "batch_id": str(batch_id),
        "status": status,
        "error": error,
        "total_chunks": total,
        "chunks_done": done,
        "rows_ok": ok,
        "rows_rejected": rejected,
        "first_rejects": [{"line_no": line, "reason": reason} for line, reason in rejects],
        "matches": matches,
        "notified": notified,
        "funnel": funnel(conn, batch_id),
        "created_at": iso(created),
        "updated_at": iso(updated),
    }
