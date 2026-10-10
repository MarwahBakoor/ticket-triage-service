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


def test_openapi_documents_the_ticket_api() -> None:
    with TestClient(app) as client:
        spec = client.get("/openapi.json").json()

    assert spec["info"]["title"] == "Ticket Triage Service"
    list_params = {p["name"]: p for p in spec["paths"]["/tickets"]["get"]["parameters"]}
    assert set(list_params) == {"category", "priority", "limit", "offset", "order"}
    order_schema = spec["components"]["schemas"]["TicketOrder"]
    assert order_schema["enum"] == ["oldest", "newest", "priority"]
    assert "404" in spec["paths"]["/tickets/{ticket_id}"]["get"]["responses"]
    assert "202" in spec["paths"]["/tickets"]["post"]["responses"]


def test_root_redirects_to_dashboard() -> None:
    with TestClient(app) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/app/"


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/app/", "text/html"),
        ("/app/app.js", "javascript"),
        ("/app/styles.css", "text/css"),
    ],
)
def test_dashboard_files_are_served(path: str, content_type: str) -> None:
    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 200
    assert content_type in response.headers["content-type"]


def test_startup_reclassifies_pending_and_interrupted_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialize_database()
    for ticket_id in ("pending", "interrupted", "classified", "failed"):
        create_ticket(ticket_id, "Double charge", "I was charged twice")
    with get_connection() as connection:
        for status in ("processing", "classified", "failed"):
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
    assert get_classification_job("pending")["status"] == "classified"
    assert get_classification_job("interrupted")["status"] == "classified"
    assert get_classification_job("classified")["status"] == "classified"
    assert get_classification_job("failed")["status"] == "failed"
    assert get_ticket("classified")["category"] is None
    assert get_ticket("failed")["category"] is None
