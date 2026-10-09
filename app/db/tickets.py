import sqlite3
from datetime import UTC, datetime
from typing import Any

from app.db.connection import get_connection
from app.llm.validation import ClassificationResult

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


def list_tickets(
    category: str | None = None,
    priority: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return tickets oldest first, optionally filtered by category and priority."""
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
    query += " ORDER BY tickets.created_at, tickets.id LIMIT ? OFFSET ?"
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


def record_failed_attempt(ticket_id: str, error: str) -> bool:
    """Count a failed attempt on a processing job and keep its latest error."""
    now = datetime.now(UTC).isoformat()
    with get_connection() as connection:
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


def complete_classification(ticket_id: str, result: ClassificationResult) -> bool:
    """Store a validated classification and complete its job in one transaction.

    Returns False without writing anything if the job is not processing.
    """
    now = datetime.now(UTC).isoformat()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE classification_jobs
            SET status = 'completed', updated_at = ?
            WHERE ticket_id = ? AND status = 'processing'
            """,
            (now, ticket_id),
        )
        if cursor.rowcount != 1:
            return False
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


def recover_unfinished_jobs() -> list[str]:
    """Reset interrupted jobs to pending and return every pending ticket id.

    Call only at startup, before any worker runs: a job still marked
    processing then belongs to a process that stopped mid-attempt. Its
    attempt count is kept, so the interrupted attempt is simply retried.
    Completed and failed jobs are never returned.
    """
    now = datetime.now(UTC).isoformat()
    with get_connection() as connection:
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
