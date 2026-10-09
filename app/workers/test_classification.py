import asyncio
from pathlib import Path

import pytest

from app.db.schema import initialize_database
from app.db.tickets import create_ticket, get_classification_job, get_ticket
from app.llm.fake import (
    MALFORMED_JSON_RESPONSE,
    VALID_RESPONSE,
    BlockingFakeLLMClient,
    FakeLLMClient,
)
from app.workers.classification import (
    DEFAULT_WORKER_COUNT,
    ClassificationWorkers,
    worker_count_from_env,
)

# Guards against a hung test; never part of the asserted behavior.
TIMEOUT_SECONDS = 5


@pytest.fixture(autouse=True)
def initialized_database(database_path: Path) -> None:
    initialize_database()


def test_worker_classifies_enqueued_ticket():
    create_ticket("t-1", "Double charge", "I was charged twice this month")

    async def scenario() -> None:
        workers = ClassificationWorkers(FakeLLMClient([VALID_RESPONSE]), 1)
        workers.start()
        workers.enqueue("t-1")
        await asyncio.wait_for(workers.join(), TIMEOUT_SECONDS)
        await workers.stop()

    asyncio.run(scenario())

    assert get_ticket("t-1")["classification_status"] == "completed"
    assert get_ticket("t-1")["category"] == "billing"


def test_worker_keeps_running_after_a_failed_ticket():
    create_ticket("t-1", "Double charge", "I was charged twice this month")
    create_ticket("t-2", "Double charge", "I was charged twice this month")
    llm = FakeLLMClient([MALFORMED_JSON_RESPONSE] * 3 + [VALID_RESPONSE])

    async def scenario() -> None:
        workers = ClassificationWorkers(llm, 1)
        workers.start()
        workers.enqueue("t-1")
        workers.enqueue("t-2")
        await asyncio.wait_for(workers.join(), TIMEOUT_SECONDS)
        await workers.stop()

    asyncio.run(scenario())

    assert get_classification_job("t-1")["status"] == "failed"
    assert get_classification_job("t-2")["status"] == "completed"


@pytest.mark.parametrize("worker_count", [1, DEFAULT_WORKER_COUNT])
def test_runs_at_most_worker_count_classifications_at_once(worker_count):
    ticket_ids = [f"t-{number}" for number in range(worker_count + 2)]
    for ticket_id in ticket_ids:
        create_ticket(ticket_id, "Subject", "Body")
    llm = BlockingFakeLLMClient()

    async def scenario() -> None:
        workers = ClassificationWorkers(llm, worker_count)
        for ticket_id in ticket_ids:
            workers.enqueue(ticket_id)
        workers.start()

        await asyncio.wait_for(llm.wait_for_in_flight(worker_count), TIMEOUT_SECONDS)
        # Every worker is now blocked inside the LLM, so none can take more work.
        assert llm.in_flight == worker_count
        assert workers.queued_count() == 2

        llm.release.set()
        await asyncio.wait_for(workers.join(), TIMEOUT_SECONDS)
        await workers.stop()

    asyncio.run(scenario())

    assert llm.max_in_flight == worker_count
    assert len(llm.prompts) == len(ticket_ids)
    for ticket_id in ticket_ids:
        assert get_classification_job(ticket_id)["status"] == "completed"


def test_stop_cancels_workers_blocked_on_the_llm():
    create_ticket("t-1", "Subject", "Body")
    llm = BlockingFakeLLMClient()

    async def scenario() -> None:
        workers = ClassificationWorkers(llm, 2)
        workers.start()
        workers.enqueue("t-1")
        await asyncio.wait_for(llm.wait_for_in_flight(1), TIMEOUT_SECONDS)
        await asyncio.wait_for(workers.stop(), TIMEOUT_SECONDS)

    asyncio.run(scenario())

    assert get_classification_job("t-1")["status"] == "processing"


def test_worker_count_must_be_positive():
    with pytest.raises(ValueError):
        ClassificationWorkers(FakeLLMClient([]), 0)


def test_worker_count_defaults_to_four(monkeypatch):
    monkeypatch.delenv("CLASSIFICATION_WORKERS", raising=False)

    assert worker_count_from_env() == 4


def test_worker_count_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("CLASSIFICATION_WORKERS", "2")

    assert worker_count_from_env() == 2


@pytest.mark.parametrize("value", ["0", "-1", "two", ""])
def test_invalid_worker_count_is_rejected(monkeypatch, value):
    monkeypatch.setenv("CLASSIFICATION_WORKERS", value)

    with pytest.raises(ValueError, match="CLASSIFICATION_WORKERS"):
        worker_count_from_env()
