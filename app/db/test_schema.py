import sqlite3
from pathlib import Path

import pytest

from app.db.connection import get_connection
from app.db.schema import initialize_database


@pytest.fixture(autouse=True)
def initialized_database(database_path: Path) -> None:
    initialize_database()


def insert_ticket(connection: sqlite3.Connection, category=None, priority=None) -> None:
    connection.execute(
        """
        INSERT INTO tickets
            (id, subject, body, category, priority, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("t-1", "Help", "Request", category, priority, "2026-10-09", "2026-10-09"),
    )


def test_tables_created_and_initialization_preserves_data():
    with get_connection() as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        assert {row["name"] for row in tables} == {"tickets", "classification_jobs"}
        insert_ticket(connection)
        connection.execute(
            """
            INSERT INTO classification_jobs (ticket_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            ("t-1", "pending", "2026-10-09", "2026-10-09"),
        )

    initialize_database()

    with get_connection() as connection:
        ticket = connection.execute("SELECT * FROM tickets").fetchone()
        assert ticket["id"] == "t-1"
        assert ticket["category"] is None
        assert ticket["priority"] is None
        assert ticket["summary"] is None
        job = connection.execute("SELECT * FROM classification_jobs").fetchone()
        assert job["status"] == "pending"
        assert job["attempts"] == 0
        assert job["last_error"] is None


@pytest.mark.parametrize(
    ("category", "priority"), [("invalid", None), (None, "urgent")]
)
def test_invalid_classification_rejected(category, priority):
    with (
        get_connection() as connection,
        pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"),
    ):
        insert_ticket(connection, category, priority)


@pytest.mark.parametrize("category", ["billing", "technical", "account", "other"])
@pytest.mark.parametrize("priority", ["low", "medium", "high"])
def test_allowed_classifications_accepted(category, priority):
    with get_connection() as connection:
        insert_ticket(connection, category, priority)


@pytest.mark.parametrize("status", ["pending", "processing", "completed", "failed"])
def test_allowed_job_statuses_accepted(status):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO classification_jobs (ticket_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            ("t-1", status, "2026-10-09", "2026-10-09"),
        )


def test_invalid_job_status_rejected():
    with (
        get_connection() as connection,
        pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"),
    ):
        connection.execute(
            """
            INSERT INTO classification_jobs (ticket_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            ("t-1", "unknown", "2026-10-09", "2026-10-09"),
        )
