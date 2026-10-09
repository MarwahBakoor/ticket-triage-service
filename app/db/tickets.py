import sqlite3
from datetime import UTC, datetime
from typing import Any

from app.db.connection import get_connection

_SELECT_TICKET = """
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
    WHERE tickets.id = ?
"""


def _fetch_ticket(
    connection: sqlite3.Connection, ticket_id: str
) -> dict[str, Any] | None:
    row = connection.execute(_SELECT_TICKET, (ticket_id,)).fetchone()
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
    assert ticket is not None
    return ticket, created


def get_ticket(ticket_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        return _fetch_ticket(connection, ticket_id)
