import asyncio

import pytest
from fastapi.testclient import TestClient

from app.db.connection import get_connection
from app.db.schema import initialize_database
from app.db.tickets import create_ticket, get_classification_job, get_ticket
from app.llm.fake import VALID_RESPONSE, FakeLLMClient
from app.main import app


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_startup_reclassifies_pending_and_interrupted_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialize_database()
    for ticket_id in ("pending", "interrupted", "completed", "failed"):
        create_ticket(ticket_id, "Double charge", "I was charged twice")
    with get_connection() as connection:
        for status in ("processing", "completed", "failed"):
            ticket_id = "interrupted" if status == "processing" else status
            connection.execute(
                "UPDATE classification_jobs SET status = ? WHERE ticket_id = ?",
                (status, ticket_id),
            )
    llm = FakeLLMClient([VALID_RESPONSE, VALID_RESPONSE])
    monkeypatch.setattr(app.state, "llm_client", llm, raising=False)

    async def scenario() -> None:
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(app.state.classification_workers.join(), 5)

    asyncio.run(scenario())

    assert len(llm.prompts) == 2
    assert get_classification_job("pending")["status"] == "completed"
    assert get_classification_job("interrupted")["status"] == "completed"
    assert get_classification_job("completed")["status"] == "completed"
    assert get_classification_job("failed")["status"] == "failed"
    assert get_ticket("completed")["category"] is None
    assert get_ticket("failed")["category"] is None
