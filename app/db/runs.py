from typing import Any

from app.db.connection import get_connection

RUN_STATUSES = ("running", "completed", "failed")


def list_runs(
    status: str | None = None,
    ticket_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return classification runs newest first, optionally filtered."""
    conditions: list[str] = []
    params: list[Any] = []
    if status is not None:
        conditions.append("status = ?")
        params.append(status)
    if ticket_id is not None:
        conditions.append("ticket_id = ?")
        params.append(ticket_id)
    query = """
        SELECT id, ticket_id, run_number, status, error, started_at, finished_at
        FROM classification_runs
    """
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with get_connection() as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def count_runs_by_status() -> dict[str, int]:
    """Return the number of runs in each status, including zero counts."""
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) AS count FROM classification_runs GROUP BY status"
        ).fetchall()
    counts = dict.fromkeys(RUN_STATUSES, 0)
    counts.update({row["status"]: row["count"] for row in rows})
    return counts
