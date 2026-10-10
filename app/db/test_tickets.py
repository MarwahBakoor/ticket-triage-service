import sqlite3
from pathlib import Path

import pytest

from app.api.schemas import TicketCategory, TicketPriority
from app.db.connection import get_connection
from app.db.schema import initialize_database
from app.db.tickets import (
    complete_classification,
    create_ticket,
    get_classification_job,
    get_ticket,
    list_tickets,
    mark_job_failed,
    mark_job_processing,
    record_failed_attempt,
    recover_unfinished_jobs,
)
from app.llm.validation import ClassificationResult


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


def classify(ticket_id: str, category: str, priority: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE tickets SET category = ?, priority = ? WHERE id = ?",
            (category, priority, ticket_id),
        )
        connection.execute(
            "UPDATE classification_jobs SET status = ? WHERE ticket_id = ?",
            ("completed", ticket_id),
        )


@pytest.fixture
def mixed_tickets() -> None:
    create_ticket("t-1", "Double charge", "Charged twice")
    create_ticket("t-2", "Refund", "Want a refund")
    create_ticket("t-3", "App crashes", "Crashes on start")
    create_ticket("t-4", "Hello", "Not classified yet")
    classify("t-1", "billing", "high")
    classify("t-2", "billing", "low")
    classify("t-3", "technical", "high")


def ids(tickets: list[dict]) -> list[str]:
    return [ticket["id"] for ticket in tickets]


def test_list_tickets_without_filters_returns_all_oldest_first(mixed_tickets):
    tickets = list_tickets()

    assert ids(tickets) == ["t-1", "t-2", "t-3", "t-4"]
    assert [ticket["classification_status"] for ticket in tickets] == [
        "completed",
        "completed",
        "completed",
        "pending",
    ]


def test_list_tickets_filters_by_category(mixed_tickets):
    assert ids(list_tickets(category="billing")) == ["t-1", "t-2"]


def test_list_tickets_filters_by_priority(mixed_tickets):
    assert ids(list_tickets(priority="high")) == ["t-1", "t-3"]


def test_list_tickets_filters_by_category_and_priority(mixed_tickets):
    assert ids(list_tickets(category="billing", priority="high")) == ["t-1"]


def test_list_tickets_applies_limit(mixed_tickets):
    assert ids(list_tickets(limit=2)) == ["t-1", "t-2"]


def test_list_tickets_applies_offset(mixed_tickets):
    assert ids(list_tickets(limit=2, offset=2)) == ["t-3", "t-4"]


def test_list_tickets_with_no_matches_returns_empty_list(mixed_tickets):
    assert list_tickets(category="account") == []


def test_list_tickets_orders_newest_first(mixed_tickets):
    assert ids(list_tickets(order="newest")) == ["t-4", "t-3", "t-2", "t-1"]


def test_list_tickets_orders_by_priority_with_unclassified_last(mixed_tickets):
    # High before low; within a priority the older ticket comes first.
    assert ids(list_tickets(order="priority")) == ["t-1", "t-3", "t-2", "t-4"]


def test_list_tickets_order_combines_with_filters_and_paging(mixed_tickets):
    assert ids(list_tickets(category="billing", order="newest")) == ["t-2", "t-1"]
    assert ids(list_tickets(order="priority", limit=2, offset=1)) == ["t-3", "t-2"]


def test_list_tickets_breaks_timestamp_ties_by_id(mixed_tickets):
    with get_connection() as connection:
        connection.execute("UPDATE tickets SET created_at = ?", (OLD_TIMESTAMP,))

    assert ids(list_tickets(order="oldest")) == ["t-1", "t-2", "t-3", "t-4"]
    assert ids(list_tickets(order="newest")) == ["t-4", "t-3", "t-2", "t-1"]


def test_list_tickets_rejects_unknown_order():
    with pytest.raises(ValueError, match="unknown ticket order"):
        list_tickets(order="tickets.id; DROP TABLE tickets")


RESULT = ClassificationResult(
    category=TicketCategory.BILLING,
    priority=TicketPriority.HIGH,
    summary="Customer was charged twice.",
)
OLD_TIMESTAMP = "2000-01-01T00:00:00+00:00"


@pytest.fixture
def processing_job() -> None:
    create_ticket("t-1", "Double charge", "Charged twice")
    with get_connection() as connection:
        connection.execute(
            "UPDATE tickets SET updated_at = ? WHERE id = ?", (OLD_TIMESTAMP, "t-1")
        )
        connection.execute(
            """
            UPDATE classification_jobs
            SET status = 'processing', updated_at = ?
            WHERE ticket_id = ?
            """,
            (OLD_TIMESTAMP, "t-1"),
        )


def set_job_status(ticket_id: str, status: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE classification_jobs SET status = ? WHERE ticket_id = ?",
            (status, ticket_id),
        )


def test_get_classification_job_returns_job():
    create_ticket("t-1", "Double charge", "Charged twice")

    job = get_classification_job("t-1")

    assert job is not None
    assert job["ticket_id"] == "t-1"
    assert job["status"] == "pending"
    assert job["attempts"] == 0
    assert job["last_error"] is None


def test_get_missing_classification_job_returns_none():
    assert get_classification_job("missing") is None


def test_mark_job_processing_claims_pending_job():
    create_ticket("t-1", "Double charge", "Charged twice")

    assert mark_job_processing("t-1") is True
    assert get_classification_job("t-1")["status"] == "processing"


@pytest.mark.parametrize("status", ["processing", "completed", "failed"])
def test_mark_job_processing_ignores_job_that_is_not_pending(status):
    create_ticket("t-1", "Double charge", "Charged twice")
    set_job_status("t-1", status)

    assert mark_job_processing("t-1") is False
    assert get_classification_job("t-1")["status"] == status


def test_mark_missing_job_processing_returns_false():
    assert mark_job_processing("missing") is False


def test_record_failed_attempt_increments_attempts_and_keeps_latest_error(
    processing_job,
):
    assert record_failed_attempt("t-1", "malformed JSON") is True
    assert record_failed_attempt("t-1", "invalid category") is True

    job = get_classification_job("t-1")
    assert job["attempts"] == 2
    assert job["last_error"] == "invalid category"
    assert job["status"] == "processing"
    assert job["updated_at"] != OLD_TIMESTAMP


def test_record_failed_attempt_does_not_touch_ticket(processing_job):
    before = get_ticket("t-1")

    record_failed_attempt("t-1", "malformed JSON")

    after = get_ticket("t-1")
    assert after == before
    assert "attempts" not in after
    assert "last_error" not in after


def test_record_failed_attempt_ignores_job_that_is_not_processing():
    create_ticket("t-1", "Double charge", "Charged twice")

    assert record_failed_attempt("t-1", "malformed JSON") is False
    assert get_classification_job("t-1")["attempts"] == 0


def test_mark_job_failed_keeps_attempts_and_error(processing_job):
    record_failed_attempt("t-1", "timeout")

    assert mark_job_failed("t-1") is True

    job = get_classification_job("t-1")
    assert job["status"] == "failed"
    assert job["attempts"] == 1
    assert job["last_error"] == "timeout"
    ticket = get_ticket("t-1")
    assert ticket["category"] is None
    assert ticket["priority"] is None
    assert ticket["summary"] is None


def test_mark_job_failed_ignores_job_that_is_not_processing():
    create_ticket("t-1", "Double charge", "Charged twice")

    assert mark_job_failed("t-1") is False
    assert get_classification_job("t-1")["status"] == "pending"


def test_complete_classification_updates_ticket_and_job(processing_job):
    assert complete_classification("t-1", RESULT) is True

    ticket = get_ticket("t-1")
    job = get_classification_job("t-1")
    assert ticket["category"] == "billing"
    assert ticket["priority"] == "high"
    assert ticket["summary"] == "Customer was charged twice."
    assert ticket["classification_status"] == "completed"
    assert job["status"] == "completed"
    assert ticket["updated_at"] != OLD_TIMESTAMP
    assert ticket["updated_at"] == job["updated_at"]


@pytest.mark.parametrize("status", ["pending", "completed", "failed"])
def test_complete_classification_ignores_job_that_is_not_processing(status):
    create_ticket("t-1", "Double charge", "Charged twice")
    set_job_status("t-1", status)

    assert complete_classification("t-1", RESULT) is False

    ticket = get_ticket("t-1")
    assert ticket["category"] is None
    assert ticket["summary"] is None
    assert get_classification_job("t-1")["status"] == status


def test_complete_classification_rolls_back_job_when_ticket_update_fails():
    # An orphaned job row makes the ticket update fail after the job update.
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO classification_jobs (ticket_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            ("t-1", "processing", OLD_TIMESTAMP, OLD_TIMESTAMP),
        )

    with pytest.raises(RuntimeError):
        complete_classification("t-1", RESULT)

    job = get_classification_job("t-1")
    assert job["status"] == "processing"
    assert job["updated_at"] == OLD_TIMESTAMP


def test_recover_unfinished_jobs_returns_pending_job():
    create_ticket("t-1", "Double charge", "Charged twice")

    assert recover_unfinished_jobs() == ["t-1"]
    assert get_classification_job("t-1")["status"] == "pending"


def test_recover_unfinished_jobs_resets_interrupted_processing_job(processing_job):
    record_failed_attempt("t-1", "LLM call failed: TimeoutError")

    assert recover_unfinished_jobs() == ["t-1"]
    job = get_classification_job("t-1")
    assert job["status"] == "pending"
    assert job["attempts"] == 1
    assert job["updated_at"] != OLD_TIMESTAMP


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_recover_unfinished_jobs_skips_finished_job(status):
    create_ticket("t-1", "Double charge", "Charged twice")
    set_job_status("t-1", status)

    assert recover_unfinished_jobs() == []
    assert get_classification_job("t-1")["status"] == status


def test_recover_unfinished_jobs_returns_only_unfinished_jobs_oldest_first():
    for ticket_id in ("t-1", "t-2", "t-3", "t-4"):
        create_ticket(ticket_id, "Subject", "Body")
    set_job_status("t-1", "completed")
    set_job_status("t-2", "processing")
    set_job_status("t-3", "failed")

    assert recover_unfinished_jobs() == ["t-2", "t-4"]
