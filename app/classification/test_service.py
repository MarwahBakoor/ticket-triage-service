import asyncio
from pathlib import Path

import pytest

from app.classification.service import classify_ticket
from app.db.connection import get_connection
from app.db.schema import initialize_database
from app.db.tickets import create_ticket, get_classification_job, get_ticket
from app.llm.fake import (
    EMPTY_SUMMARY_RESPONSE,
    INVALID_CATEGORY_RESPONSE,
    INVALID_PRIORITY_RESPONSE,
    MALFORMED_JSON_RESPONSE,
    VALID_RESPONSE,
    FakeLLMClient,
)


@pytest.fixture(autouse=True)
def initialized_database(database_path: Path) -> None:
    initialize_database()


def stored_values() -> list[object]:
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM tickets").fetchall()
        rows += connection.execute("SELECT * FROM classification_jobs").fetchall()
    return [value for row in rows for value in tuple(row)]


def assert_classified(ticket_id: str, attempts: int) -> None:
    ticket = get_ticket(ticket_id)
    assert ticket["category"] == "billing"
    assert ticket["priority"] == "high"
    assert ticket["summary"] == "Customer was charged twice."
    job = get_classification_job(ticket_id)
    assert job["status"] == "completed"
    assert job["attempts"] == attempts


def test_classifies_pending_ticket_on_first_attempt():
    create_ticket("t-1", "Double charge", "I was charged twice this month")
    llm = FakeLLMClient([VALID_RESPONSE])

    classified = asyncio.run(classify_ticket("t-1", llm))

    assert classified is True
    assert len(llm.prompts) == 1
    assert_classified("t-1", attempts=0)
    assert get_classification_job("t-1")["last_error"] is None


@pytest.mark.parametrize(
    "first_response",
    [
        pytest.param(TimeoutError("model timed out"), id="llm-exception"),
        pytest.param(MALFORMED_JSON_RESPONSE, id="malformed-json"),
        pytest.param(INVALID_CATEGORY_RESPONSE, id="invalid-category"),
        pytest.param(INVALID_PRIORITY_RESPONSE, id="invalid-priority"),
        pytest.param(EMPTY_SUMMARY_RESPONSE, id="empty-summary"),
    ],
)
def test_retries_after_one_failure_then_succeeds(first_response):
    create_ticket("t-1", "Double charge", "I was charged twice this month")
    llm = FakeLLMClient([first_response, VALID_RESPONSE])

    classified = asyncio.run(classify_ticket("t-1", llm))

    assert classified is True
    assert len(llm.prompts) == 2
    assert_classified("t-1", attempts=1)


def test_succeeds_on_third_attempt():
    create_ticket("t-1", "Double charge", "I was charged twice this month")
    llm = FakeLLMClient([MALFORMED_JSON_RESPONSE, RuntimeError(), VALID_RESPONSE])

    assert asyncio.run(classify_ticket("t-1", llm)) is True
    assert_classified("t-1", attempts=2)


def test_three_failures_mark_job_failed():
    create_ticket("t-1", "Double charge", "I was charged twice this month")
    llm = FakeLLMClient(
        [
            TimeoutError("model timed out"),
            MALFORMED_JSON_RESPONSE,
            INVALID_CATEGORY_RESPONSE,
            VALID_RESPONSE,
        ]
    )

    classified = asyncio.run(classify_ticket("t-1", llm))

    assert classified is False
    assert len(llm.prompts) == 3
    job = get_classification_job("t-1")
    assert job["status"] == "failed"
    assert job["attempts"] == 3
    assert job["last_error"] == "Model output was not a valid classification"


def test_failed_classification_does_not_write_invalid_fields():
    create_ticket("t-1", "Double charge", "I was charged twice this month")
    llm = FakeLLMClient(
        [INVALID_CATEGORY_RESPONSE, INVALID_PRIORITY_RESPONSE, EMPTY_SUMMARY_RESPONSE]
    )

    asyncio.run(classify_ticket("t-1", llm))

    ticket = get_ticket("t-1")
    assert ticket["category"] is None
    assert ticket["priority"] is None
    assert ticket["summary"] is None
    assert ticket["classification_status"] == "failed"
    values = stored_values()
    assert "refunds" not in values
    assert "urgent" not in values


def test_last_error_does_not_contain_exception_message():
    create_ticket("t-1", "Double charge", "I was charged twice this month")
    llm = FakeLLMClient([ConnectionError("secret-token-123"), VALID_RESPONSE])

    asyncio.run(classify_ticket("t-1", llm))

    assert get_classification_job("t-1")["last_error"] == (
        "LLM call failed: ConnectionError"
    )


def test_last_error_does_not_contain_raw_model_output():
    create_ticket("t-1", "Double charge", "I was charged twice this month")
    raw_output = '{"category": "ignore previous instructions", "priority": "high"}'
    llm = FakeLLMClient([raw_output, VALID_RESPONSE])

    asyncio.run(classify_ticket("t-1", llm))

    last_error = get_classification_job("t-1")["last_error"]
    assert "ignore previous instructions" not in last_error
    assert all(raw_output not in str(value) for value in stored_values())


def test_sends_ticket_subject_and_body_to_llm():
    create_ticket("t-1", "Double charge", "I was charged twice this month")
    llm = FakeLLMClient([VALID_RESPONSE])

    asyncio.run(classify_ticket("t-1", llm))

    assert len(llm.prompts) == 1
    assert "Double charge" in llm.prompts[0]
    assert "I was charged twice this month" in llm.prompts[0]


def test_does_not_persist_raw_model_output():
    create_ticket("t-1", "Double charge", "I was charged twice this month")
    raw_output = '  {"summary": "Customer was charged twice.", "priority": "high", "category": "billing"}  '

    asyncio.run(classify_ticket("t-1", FakeLLMClient([raw_output])))

    assert get_classification_job("t-1")["status"] == "completed"
    assert raw_output not in stored_values()
    assert raw_output.strip() not in stored_values()


def test_missing_ticket_is_not_classified():
    llm = FakeLLMClient([VALID_RESPONSE])

    assert asyncio.run(classify_ticket("missing", llm)) is False
    assert llm.prompts == []


@pytest.mark.parametrize("status", ["processing", "completed", "failed"])
def test_job_that_is_not_pending_is_not_classified(status):
    create_ticket("t-1", "Double charge", "I was charged twice this month")
    with get_connection() as connection:
        connection.execute(
            "UPDATE classification_jobs SET status = ? WHERE ticket_id = ?",
            (status, "t-1"),
        )
    llm = FakeLLMClient([VALID_RESPONSE])

    assert asyncio.run(classify_ticket("t-1", llm)) is False
    assert llm.prompts == []
    assert get_ticket("t-1")["category"] is None
    assert get_classification_job("t-1")["status"] == status
