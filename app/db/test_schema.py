import pytest

from app.db.connection import get_connection
from app.db.schema import initialize_database


def test_initialize_database_is_safe_to_repeat():
    initialize_database()
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO tickets (id, subject, body, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("t-1", "Hello", "Body", "2026-10-10", "2026-10-10"),
        )

    initialize_database()

    with get_connection() as connection:
        count = connection.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    assert count == 1


def test_initialize_database_rejects_database_with_old_job_statuses():
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE classification_jobs (
                ticket_id TEXT PRIMARY KEY,
                status TEXT NOT NULL
                    CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    with pytest.raises(RuntimeError, match="older version"):
        initialize_database()
