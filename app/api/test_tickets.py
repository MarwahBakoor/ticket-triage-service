from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.db.connection import get_connection
from app.db.tickets import get_ticket
from app.main import app

TICKET = {
    "id": "t-1",
    "subject": "Cannot log in",
    "body": "Password reset did not work",
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


def count_rows(table: str) -> int:
    with get_connection() as connection:
        return connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()[
            "count"
        ]


def test_create_ticket_returns_pending_ticket(client: TestClient) -> None:
    response = client.post("/tickets", json=TICKET)

    assert response.status_code == 202
    body = response.json()
    assert body["id"] == "t-1"
    assert body["subject"] == "Cannot log in"
    assert body["body"] == "Password reset did not work"
    assert body["classification_status"] == "pending"
    assert body["category"] is None
    assert body["priority"] is None
    assert body["summary"] is None
    assert body["created_at"]
    assert body["updated_at"]


def test_create_ticket_persists_ticket_and_pending_job(client: TestClient) -> None:
    client.post("/tickets", json=TICKET)

    ticket = get_ticket("t-1")
    assert ticket is not None
    assert ticket["classification_status"] == "pending"
    assert count_rows("tickets") == 1
    assert count_rows("classification_jobs") == 1


def test_duplicate_ticket_returns_existing_ticket(client: TestClient) -> None:
    first = client.post("/tickets", json=TICKET)

    second = client.post("/tickets", json=TICKET)

    assert second.status_code == 202
    assert second.json() == first.json()
    assert count_rows("tickets") == 1
    assert count_rows("classification_jobs") == 1


def test_duplicate_ticket_does_not_modify_existing_ticket(client: TestClient) -> None:
    first = client.post("/tickets", json=TICKET)

    second = client.post(
        "/tickets",
        json={"id": "t-1", "subject": "Different subject", "body": "Different body"},
    )

    assert second.status_code == 202
    assert second.json() == first.json()
    ticket = get_ticket("t-1")
    assert ticket is not None
    assert ticket["subject"] == "Cannot log in"
    assert ticket["body"] == "Password reset did not work"


@pytest.mark.parametrize(
    "payload",
    [
        {"subject": "Cannot log in", "body": "Password reset did not work"},
        {"id": "t-1", "body": "Password reset did not work"},
        {"id": "t-1", "subject": "Cannot log in"},
        {"id": "", "subject": "Cannot log in", "body": "Password reset did not work"},
    ],
)
def test_invalid_ticket_is_rejected_and_not_stored(
    client: TestClient, payload: dict[str, str]
) -> None:
    response = client.post("/tickets", json=payload)

    assert response.status_code == 422
    assert count_rows("tickets") == 0
    assert count_rows("classification_jobs") == 0


def test_get_ticket_returns_classified_ticket(client: TestClient) -> None:
    client.post("/tickets", json=TICKET)
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE tickets SET category = ?, priority = ?, summary = ?
            WHERE id = ?
            """,
            ("account", "high", "User cannot reset password", "t-1"),
        )
        connection.execute(
            "UPDATE classification_jobs SET status = ? WHERE ticket_id = ?",
            ("completed", "t-1"),
        )

    response = client.get("/tickets/t-1")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "t-1"
    assert body["subject"] == "Cannot log in"
    assert body["body"] == "Password reset did not work"
    assert body["category"] == "account"
    assert body["priority"] == "high"
    assert body["summary"] == "User cannot reset password"
    assert body["classification_status"] == "completed"


def test_get_pending_ticket_matches_created_response(client: TestClient) -> None:
    created = client.post("/tickets", json=TICKET)

    response = client.get("/tickets/t-1")

    assert response.status_code == 200
    assert response.json() == created.json()
    assert response.json()["classification_status"] == "pending"
    assert response.json()["category"] is None
    assert response.json()["priority"] is None
    assert response.json()["summary"] is None


def test_get_missing_ticket_returns_404(client: TestClient) -> None:
    response = client.get("/tickets/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Ticket not found"}
