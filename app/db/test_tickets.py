import sqlite3
from pathlib import Path

import pytest

from app.db.connection import get_connection
from app.db.schema import initialize_database
from app.db.tickets import create_ticket, get_ticket


@pytest.fixture(autouse=True)
def initialized_database(database_path: Path) -> None:
    initialize_database()


def count_rows(table: str) -> int:
    with get_connection() as connection:
        return connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()[
            "count"
        ]


def test_ticket_and_classification_job_created_together():
    ticket, created = create_ticket("t-1", "Cannot log in", "Password reset failed")

    assert created is True
    assert ticket["id"] == "t-1"
    assert ticket["subject"] == "Cannot log in"
    assert ticket["body"] == "Password reset failed"
    with get_connection() as connection:
        job = connection.execute(
            "SELECT * FROM classification_jobs WHERE ticket_id = ?", ("t-1",)
        ).fetchone()
    assert job is not None
    assert job["attempts"] == 0
    assert job["last_error"] is None


def test_new_ticket_classification_status_is_pending():
    ticket, _ = create_ticket("t-1", "Cannot log in", "Password reset failed")

    assert ticket["classification_status"] == "pending"
    assert ticket["category"] is None
    assert ticket["priority"] is None
    assert ticket["summary"] is None
    assert get_ticket("t-1") == ticket


def test_get_missing_ticket_returns_none():
    assert get_ticket("missing") is None


def test_duplicate_ticket_does_not_create_another_row():
    create_ticket("t-1", "Cannot log in", "Password reset failed")

    _, created = create_ticket("t-1", "Cannot log in", "Password reset failed")

    assert created is False
    assert count_rows("tickets") == 1
    assert count_rows("classification_jobs") == 1


def test_duplicate_ticket_does_not_replace_original_content():
    original, _ = create_ticket("t-1", "Cannot log in", "Password reset failed")

    ticket, created = create_ticket("t-1", "Different subject", "Different body")

    assert created is False
    assert ticket == original
    assert get_ticket("t-1") == original


def test_existing_ticket_without_job_raises():
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO tickets (id, subject, body, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "t-1",
                "Cannot log in",
                "Password reset failed",
                "2026-10-09",
                "2026-10-09",
            ),
        )

    with pytest.raises(RuntimeError):
        create_ticket("t-1", "Cannot log in", "Password reset failed")


def test_failed_job_insert_leaves_no_ticket_row():
    # An orphaned job row makes the job insert fail after the ticket insert.
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO classification_jobs (ticket_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            ("t-1", "completed", "2026-10-09", "2026-10-09"),
        )

    with pytest.raises(sqlite3.IntegrityError):
        create_ticket("t-1", "Cannot log in", "Password reset failed")

    assert count_rows("tickets") == 0
    assert count_rows("classification_jobs") == 1
