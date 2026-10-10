import asyncio

import pytest

from app.classification.service import classify_claimed_ticket
from app.db.connection import get_connection
from app.db.schema import initialize_database
from app.db.tickets import (
    claim_next_job,
    create_ticket,
    get_classification_job,
    reset_for_reclassification,
)
from app.llm.fake import MALFORMED_JSON_RESPONSE, VALID_RESPONSE, FakeLLMClient


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


def test_database_with_removed_last_error_column_still_works():
    # Databases from before last_error was dropped keep the column unused.
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE classification_jobs (
                ticket_id TEXT PRIMARY KEY,
                status TEXT NOT NULL
                    CHECK (status IN ('pending', 'processing', 'classified', 'failed')),
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
    initialize_database()
    create_ticket("t-1", "Double charge", "I was charged twice")
    llm = FakeLLMClient([MALFORMED_JSON_RESPONSE, VALID_RESPONSE])

    assert claim_next_job() == "t-1"
    assert asyncio.run(classify_claimed_ticket("t-1", llm)) is True

    assert get_classification_job("t-1")["status"] == "classified"
    assert reset_for_reclassification("t-1") is True
