import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db.connection import get_connection
from app.db.schema import initialize_database
from app.db.tickets import get_ticket
from app.llm.fake import (
    MALFORMED_JSON_RESPONSE,
    VALID_RESPONSE,
    BlockingFakeLLMClient,
    FakeLLMClient,
)
from app.main import app
from app.workers.classification import ClassificationWorkers

SAMPLES_PATH = Path(__file__).parents[2] / "sample_data" / "tickets.json"

# Guards against a hung test; never part of the asserted behavior.
TIMEOUT_SECONDS = 5

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


def test_ticket_with_empty_subject_is_accepted(client: TestClient) -> None:
    response = client.post(
        "/tickets", json={"id": "t-1", "subject": "", "body": "asdf"}
    )

    assert response.status_code == 202
    assert response.json()["subject"] == ""


def test_sample_tickets_load_and_reload_without_duplicates(client: TestClient) -> None:
    samples = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    expected_ids = [f"t-{number}" for number in range(1001, 1011)]

    for _ in range(2):
        responses = [client.post("/tickets", json=ticket) for ticket in samples]
        assert [response.status_code for response in responses] == [202] * 10

    assert [ticket["id"] for ticket in samples] == expected_ids
    assert count_rows("tickets") == 10
    assert count_rows("classification_jobs") == 10


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
            ("classified", "t-1"),
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
    assert body["classification_status"] == "classified"


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


def classify(ticket_id: str, category: str, priority: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE tickets SET category = ?, priority = ? WHERE id = ?",
            (category, priority, ticket_id),
        )
        connection.execute(
            "UPDATE classification_jobs SET status = ? WHERE ticket_id = ?",
            ("classified", ticket_id),
        )


@pytest.fixture
def mixed_tickets(client: TestClient) -> None:
    for ticket_id in ("t-1", "t-2", "t-3", "t-4"):
        client.post(
            "/tickets",
            json={"id": ticket_id, "subject": "Subject", "body": "Body"},
        )
    classify("t-1", "billing", "high")
    classify("t-2", "billing", "low")
    classify("t-3", "technical", "high")


def list_ids(client: TestClient, params: dict[str, str | int]) -> list[str]:
    response = client.get("/tickets", params=params)
    assert response.status_code == 200
    return [ticket["id"] for ticket in response.json()]


def test_list_tickets_without_filters_returns_all(
    client: TestClient, mixed_tickets: None
) -> None:
    response = client.get("/tickets")

    assert response.status_code == 200
    body = response.json()
    assert [ticket["id"] for ticket in body] == ["t-1", "t-2", "t-3", "t-4"]
    assert body[0]["category"] == "billing"
    assert body[0]["priority"] == "high"
    assert body[0]["classification_status"] == "classified"
    assert body[3]["category"] is None
    assert body[3]["classification_status"] == "pending"


def test_list_tickets_filters_by_category(
    client: TestClient, mixed_tickets: None
) -> None:
    assert list_ids(client, {"category": "billing"}) == ["t-1", "t-2"]


def test_list_tickets_filters_by_priority(
    client: TestClient, mixed_tickets: None
) -> None:
    assert list_ids(client, {"priority": "high"}) == ["t-1", "t-3"]


def test_list_tickets_filters_by_category_and_priority(
    client: TestClient, mixed_tickets: None
) -> None:
    assert list_ids(client, {"category": "billing", "priority": "high"}) == ["t-1"]


def test_list_tickets_applies_limit(client: TestClient, mixed_tickets: None) -> None:
    assert list_ids(client, {"limit": 2}) == ["t-1", "t-2"]


def test_list_tickets_applies_offset(client: TestClient, mixed_tickets: None) -> None:
    assert list_ids(client, {"offset": 1}) == ["t-2", "t-3", "t-4"]
    assert list_ids(client, {"limit": 2, "offset": 2}) == ["t-3", "t-4"]


def test_list_tickets_orders_newest_first(
    client: TestClient, mixed_tickets: None
) -> None:
    assert list_ids(client, {"order": "newest"}) == ["t-4", "t-3", "t-2", "t-1"]


def test_list_tickets_orders_by_priority(
    client: TestClient, mixed_tickets: None
) -> None:
    assert list_ids(client, {"order": "priority"}) == ["t-1", "t-3", "t-2", "t-4"]


def test_list_tickets_order_combines_with_filters(
    client: TestClient, mixed_tickets: None
) -> None:
    assert list_ids(client, {"category": "billing", "order": "newest"}) == [
        "t-2",
        "t-1",
    ]


def test_list_tickets_defaults_to_20_results(client: TestClient) -> None:
    for number in range(21):
        client.post(
            "/tickets",
            json={"id": f"t-{number:02d}", "subject": "Subject", "body": "Body"},
        )

    assert len(list_ids(client, {})) == 20
    assert len(list_ids(client, {"limit": 100})) == 21


@pytest.mark.parametrize(
    "params",
    [
        {"category": "shipping"},
        {"priority": "urgent"},
        {"limit": 0},
        {"limit": 101},
        {"limit": "ten"},
        {"offset": -1},
        {"offset": "one"},
        {"order": "random"},
        {"order": "created_at desc"},
    ],
)
def test_list_tickets_rejects_invalid_query_values(
    client: TestClient, params: dict[str, str | int]
) -> None:
    response = client.get("/tickets", params=params)

    assert response.status_code == 422


async def post_ticket(app_client: httpx.AsyncClient) -> httpx.Response:
    return await app_client.post("/tickets", json=TICKET)


def async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def test_classification_runs_after_the_create_request_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = BlockingFakeLLMClient()
    monkeypatch.setattr(app.state, "llm_client", llm, raising=False)

    async def scenario() -> None:
        async with app.router.lifespan_context(app), async_client() as client:
            # The LLM cannot answer yet, so a response proves the request
            # did not wait for classification.
            response = await asyncio.wait_for(post_ticket(client), TIMEOUT_SECONDS)
            assert response.status_code == 202
            assert response.json()["classification_status"] == "pending"
            assert response.json()["category"] is None

            await asyncio.wait_for(llm.wait_for_in_flight(1), TIMEOUT_SECONDS)
            llm.release.set()
            await asyncio.wait_for(
                app.state.classification_workers.join(), TIMEOUT_SECONDS
            )

            classified = await client.get("/tickets/t-1")
            assert classified.json()["classification_status"] == "classified"
            assert classified.json()["category"] == "billing"
            assert classified.json()["priority"] == "high"
            assert classified.json()["summary"] == "Customer was charged twice."

    asyncio.run(scenario())
    assert len(llm.prompts) == 1


def test_failed_classification_is_visible_with_no_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLLMClient([MALFORMED_JSON_RESPONSE] * 3)
    monkeypatch.setattr(app.state, "llm_client", llm, raising=False)

    async def scenario() -> httpx.Response:
        async with app.router.lifespan_context(app), async_client() as client:
            await post_ticket(client)
            await asyncio.wait_for(
                app.state.classification_workers.join(), TIMEOUT_SECONDS
            )
            return await client.get("/tickets/t-1")

    body = asyncio.run(scenario()).json()
    assert body["classification_status"] == "failed"
    assert body["category"] is None
    assert body["priority"] is None
    assert body["summary"] is None


@pytest.fixture
def idle_workers(monkeypatch: pytest.MonkeyPatch) -> ClassificationWorkers:
    """Workers that are never started, so enqueued ids stay observable."""
    initialize_database()
    workers = ClassificationWorkers(FakeLLMClient([]), 1)
    monkeypatch.setattr(app.state, "classification_workers", workers, raising=False)
    return workers


def test_new_ticket_is_enqueued_once(idle_workers: ClassificationWorkers) -> None:
    async def scenario() -> None:
        async with async_client() as client:
            await post_ticket(client)

    asyncio.run(scenario())

    assert idle_workers.queued_count() == 1


def test_duplicate_ticket_is_not_enqueued_again(
    idle_workers: ClassificationWorkers,
) -> None:
    async def scenario() -> None:
        async with async_client() as client:
            await post_ticket(client)
            await post_ticket(client)

    asyncio.run(scenario())

    assert idle_workers.queued_count() == 1
    assert count_rows("classification_jobs") == 1


def test_concurrent_duplicate_tickets_are_enqueued_once(
    idle_workers: ClassificationWorkers,
) -> None:
    async def scenario() -> list[httpx.Response]:
        async with async_client() as client:
            return await asyncio.gather(*(post_ticket(client) for _ in range(5)))

    responses = asyncio.run(scenario())

    assert all(response.status_code == 202 for response in responses)
    assert idle_workers.queued_count() == 1
    assert count_rows("tickets") == 1
    assert count_rows("classification_jobs") == 1


def set_job_status(ticket_id: str, status: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE classification_jobs SET status = ? WHERE ticket_id = ?",
            (status, ticket_id),
        )


@pytest.mark.parametrize("status", ["classified", "failed"])
def test_reclassify_returns_finished_ticket_to_pending(
    client: TestClient, status: str
) -> None:
    client.post("/tickets", json=TICKET)
    set_job_status("t-1", status)

    response = client.post("/tickets/t-1/reclassify")

    assert response.status_code == 202
    body = response.json()
    assert body["classification_status"] == "pending"
    assert body["category"] is None


def test_reclassify_enqueues_ticket_once(idle_workers: ClassificationWorkers) -> None:
    async def scenario() -> list[httpx.Response]:
        async with async_client() as client:
            await post_ticket(client)
            set_job_status("t-1", "failed")
            return await asyncio.gather(
                *(client.post("/tickets/t-1/reclassify") for _ in range(3))
            )

    responses = asyncio.run(scenario())

    assert sorted(response.status_code for response in responses) == [202, 409, 409]
    # One id from the submission, one from the reclassification.
    assert idle_workers.queued_count() == 2


@pytest.mark.parametrize("status", ["pending", "processing"])
def test_reclassify_unfinished_ticket_is_conflict(
    client: TestClient, status: str
) -> None:
    client.post("/tickets", json=TICKET)
    set_job_status("t-1", status)

    response = client.post("/tickets/t-1/reclassify")

    assert response.status_code == 409
    assert response.json() == {"detail": "Ticket is still being classified"}
    assert get_ticket("t-1")["classification_status"] == status


def test_reclassify_missing_ticket_is_not_found(client: TestClient) -> None:
    response = client.post("/tickets/missing/reclassify")

    assert response.status_code == 404
    assert response.json() == {"detail": "Ticket not found"}


def test_failed_ticket_is_classified_after_reclassify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLLMClient([MALFORMED_JSON_RESPONSE] * 3 + [VALID_RESPONSE])
    monkeypatch.setattr(app.state, "llm_client", llm, raising=False)

    async def scenario() -> httpx.Response:
        async with app.router.lifespan_context(app), async_client() as client:
            workers = app.state.classification_workers
            await post_ticket(client)
            await asyncio.wait_for(workers.join(), TIMEOUT_SECONDS)
            await client.post("/tickets/t-1/reclassify")
            await asyncio.wait_for(workers.join(), TIMEOUT_SECONDS)
            return await client.get("/tickets/t-1")

    body = asyncio.run(scenario()).json()

    assert body["classification_status"] == "classified"
    assert body["category"] == "billing"
    assert count_rows("classification_runs") == 4
