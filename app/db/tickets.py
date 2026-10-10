import sqlite3
from datetime import UTC, datetime
from typing import Any

from app.db.connection import get_connection
from app.llm.validation import ClassificationResult

# Run errors are fixed text, like job errors, so model output never leaks in.
RUN_INTERRUPTED = "Interrupted before finishing"
JOB_NOT_PROCESSING = "Job was no longer processing"

_SELECT_TICKETS = """
    SELECT
        tickets.id,
        tickets.subject,
        tickets.body,
        tickets.category,
        tickets.priority,
        tickets.summary,
        tickets.created_at,
        tickets.updated_at,
        classification_jobs.status AS classification_status
    FROM tickets
    JOIN classification_jobs ON classification_jobs.ticket_id = tickets.id
"""


def _fetch_ticket(
    connection: sqlite3.Connection, ticket_id: str
) -> dict[str, Any] | None:
    row = connection.execute(
        _SELECT_TICKETS + " WHERE tickets.id = ?", (ticket_id,)
    ).fetchone()
    return dict(row) if row is not None else None


def create_ticket(
    ticket_id: str, subject: str, body: str
) -> tuple[dict[str, Any], bool]:
    """Create a ticket and its pending classification job in one transaction.

    Returns the stored ticket and whether it was newly created. An existing
    ticket with the same id is returned unchanged.
    """
    now = datetime.now(UTC).isoformat()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO tickets (id, subject, body, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (id) DO NOTHING
            """,
            (ticket_id, subject, body, now, now),
        )
        created = cursor.rowcount == 1
        if created:
            connection.execute(
                """
                INSERT INTO classification_jobs
                    (ticket_id, status, created_at, updated_at)
                VALUES (?, 'pending', ?, ?)
                """,
                (ticket_id, now, now),
            )
        ticket = _fetch_ticket(connection, ticket_id)
    if ticket is None:
        raise RuntimeError(f"ticket {ticket_id!r} has no classification job")
    return ticket, created


def get_ticket(ticket_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        return _fetch_ticket(connection, ticket_id)


# Fixed clauses only: the requested order selects one, it never becomes SQL.
# Every clause ends with tickets.id so pages are stable when timestamps tie.
_ORDER_BY = {
    "oldest": "tickets.created_at, tickets.id",
    "newest": "tickets.created_at DESC, tickets.id DESC",
    "priority": """
        CASE tickets.priority
            WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3
        END,
        tickets.created_at,
        tickets.id
    """,
}


def list_tickets(
    category: str | None = None,
    priority: str | None = None,
    limit: int = 20,
    offset: int = 0,
    order: str = "oldest",
) -> list[dict[str, Any]]:
    """Return tickets in the given order, optionally filtered.

    `order` is "oldest" (the default), "newest" or "priority" (high, medium,
    low, then unclassified, oldest first within each).
    """
    if order not in _ORDER_BY:
        raise ValueError(f"unknown ticket order {order!r}")
    conditions: list[str] = []
    params: list[Any] = []
    if category is not None:
        conditions.append("tickets.category = ?")
        params.append(category)
    if priority is not None:
        conditions.append("tickets.priority = ?")
        params.append(priority)
    query = _SELECT_TICKETS
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += f" ORDER BY {_ORDER_BY[order]} LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with get_connection() as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_classification_job(ticket_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT ticket_id, status, attempts, last_error, created_at, updated_at
            FROM classification_jobs
            WHERE ticket_id = ?
            """,
            (ticket_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def mark_job_processing(ticket_id: str) -> bool:
    """Claim a pending job. Returns False if the job is missing or not pending."""
    now = datetime.now(UTC).isoformat()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE classification_jobs
            SET status = 'processing', updated_at = ?
            WHERE ticket_id = ? AND status = 'pending'
            """,
            (now, ticket_id),
        )
    return cursor.rowcount == 1


def start_run(ticket_id: str) -> int | None:
    """Record a new running attempt for a processing job.

    Returns the run id, or None if the job is missing or not processing.
    Runs are numbered per ticket from 1.
    """
    now = datetime.now(UTC).isoformat()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO classification_runs (ticket_id, run_number, status, started_at)
            SELECT
                ?,
                (
                    SELECT COALESCE(MAX(run_number), 0) + 1
                    FROM classification_runs
                    WHERE ticket_id = ?
                ),
                'running',
                ?
            WHERE EXISTS (
                SELECT 1 FROM classification_jobs
                WHERE ticket_id = ? AND status = 'processing'
            )
            """,
            (ticket_id, ticket_id, now, ticket_id),
        )
    return cursor.lastrowid if cursor.rowcount == 1 else None


def _finish_run(
    connection: sqlite3.Connection,
    ticket_id: str,
    run_id: int,
    status: str,
    error: str | None,
    now: str,
) -> None:
    cursor = connection.execute(
        """
        UPDATE classification_runs
        SET status = ?, error = ?, finished_at = ?
        WHERE id = ? AND ticket_id = ? AND status = 'running'
        """,
        (status, error, now, run_id, ticket_id),
    )
    if cursor.rowcount != 1:
        raise RuntimeError(f"run {run_id} is not a running run of {ticket_id!r}")


def record_failed_attempt(ticket_id: str, run_id: int, error: str) -> bool:
    """Fail a run, count the attempt on its job and keep the latest error.

    The run is always recorded as failed. Returns False if the job is no
    longer processing, in which case the job is left unchanged.
    """
    now = datetime.now(UTC).isoformat()
    with get_connection() as connection:
        _finish_run(connection, ticket_id, run_id, "failed", error, now)
        cursor = connection.execute(
            """
            UPDATE classification_jobs
            SET attempts = attempts + 1, last_error = ?, updated_at = ?
            WHERE ticket_id = ? AND status = 'processing'
            """,
            (error, now, ticket_id),
        )
    return cursor.rowcount == 1


def mark_job_failed(ticket_id: str) -> bool:
    """Mark a processing job as permanently failed."""
    now = datetime.now(UTC).isoformat()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE classification_jobs
            SET status = 'failed', updated_at = ?
            WHERE ticket_id = ? AND status = 'processing'
            """,
            (now, ticket_id),
        )
    return cursor.rowcount == 1


def complete_classification(
    ticket_id: str, run_id: int, result: ClassificationResult
) -> bool:
    """Store a validated classification, completing its run and job together.

    If the job is no longer processing, nothing is stored on the ticket or
    job, the run is recorded as failed, and False is returned.
    """
    now = datetime.now(UTC).isoformat()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE classification_jobs
            SET status = 'classified', updated_at = ?
            WHERE ticket_id = ? AND status = 'processing'
            """,
            (now, ticket_id),
        )
        if cursor.rowcount != 1:
            _finish_run(
                connection, ticket_id, run_id, "failed", JOB_NOT_PROCESSING, now
            )
            return False
        _finish_run(connection, ticket_id, run_id, "completed", None, now)
        cursor = connection.execute(
            """
            UPDATE tickets
            SET category = ?, priority = ?, summary = ?, updated_at = ?
            WHERE id = ?
            """,
            (result.category, result.priority, result.summary, now, ticket_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"classification job {ticket_id!r} has no ticket")
    return True


def reset_for_reclassification(ticket_id: str) -> bool:
    """Return a classified or failed job to pending with fresh attempts.

    The old classification is cleared in the same transaction, so a ticket
    only ever shows a result produced by its current job. Earlier runs are
    kept as history. Returns False if the ticket is missing or its job is
    still pending or processing, in which case nothing changes.
    """
    now = datetime.now(UTC).isoformat()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE classification_jobs
            SET status = 'pending', attempts = 0, last_error = NULL, updated_at = ?
            WHERE ticket_id = ? AND status IN ('classified', 'failed')
            """,
            (now, ticket_id),
        )
        if cursor.rowcount != 1:
            return False
        cursor = connection.execute(
            """
            UPDATE tickets
            SET category = NULL, priority = NULL, summary = NULL, updated_at = ?
            WHERE id = ?
            """,
            (now, ticket_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"classification job {ticket_id!r} has no ticket")
    return True


def recover_unfinished_jobs() -> list[str]:
    """Reset interrupted jobs to pending and return every pending ticket id.

    Call only at startup, before any worker runs: a job still marked
    processing then belongs to a process that stopped mid-attempt. Its
    attempt count is kept, so the interrupted attempt is simply retried.
    Its unfinished run is recorded as failed. Completed and failed jobs are
    never returned.
    """
    now = datetime.now(UTC).isoformat()
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE classification_runs
            SET status = 'failed', error = ?, finished_at = ?
            WHERE status = 'running'
            """,
            (RUN_INTERRUPTED, now),
        )
        connection.execute(
            """
            UPDATE classification_jobs
            SET status = 'pending', updated_at = ?
            WHERE status = 'processing'
            """,
            (now,),
        )
        rows = connection.execute(
            """
            SELECT ticket_id FROM classification_jobs
            WHERE status = 'pending'
            ORDER BY created_at, ticket_id
            """
        ).fetchall()
    return [row["ticket_id"] for row in rows]
