import asyncio
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.llm.fake import MALFORMED_JSON_RESPONSE, VALID_RESPONSE, FakeLLMClient
from app.main import app
from tests.conftest import wait_until_idle


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


def classify_tickets(
    monkeypatch: pytest.MonkeyPatch, responses: list[str], ticket_ids: list[str]
) -> None:
    """Submit tickets through the API and wait for the workers to finish.

    One worker handles the tickets in order, so each takes its scripted
    responses before the next ticket starts.
    """
    monkeypatch.setenv("CLASSIFICATION_WORKERS", "1")
    monkeypatch.setattr(app.state, "llm_client", FakeLLMClient(responses))

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://test") as http,
        ):
            for ticket_id in ticket_ids:
                await http.post(
                    "/tickets",
                    json={"id": ticket_id, "subject": "Charged twice", "body": "Help"},
                )
            await wait_until_idle()

    asyncio.run(scenario())


def test_runs_are_empty_before_any_classification(client: TestClient) -> None:
    assert client.get("/internal/runs").json() == []
    assert client.get("/internal/runs/summary").json() == {
        "running": 0,
        "completed": 0,
        "failed": 0,
        "total": 0,
    }


def test_each_attempt_is_listed_as_a_run(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    classify_tickets(monkeypatch, [MALFORMED_JSON_RESPONSE, VALID_RESPONSE], ["t-1"])

    runs = client.get("/internal/runs").json()

    assert [(r["run_number"], r["status"]) for r in runs] == [
        (2, "completed"),
        (1, "failed"),
    ]
    assert runs[1]["error"] == "Model output was not a valid classification"
    assert runs[0]["error"] is None
    assert all(run["ticket_id"] == "t-1" and run["finished_at"] for run in runs)


def test_summary_counts_runs_by_status(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    classify_tickets(
        monkeypatch,
        [MALFORMED_JSON_RESPONSE] * 3 + [VALID_RESPONSE],
        ["t-1", "t-2"],
    )

    assert client.get("/internal/runs/summary").json() == {
        "running": 0,
        "completed": 1,
        "failed": 3,
        "total": 4,
    }


def test_runs_can_be_filtered_and_paged(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    classify_tickets(
        monkeypatch,
        [MALFORMED_JSON_RESPONSE] * 3 + [VALID_RESPONSE],
        ["t-1", "t-2"],
    )

    failed = client.get("/internal/runs", params={"status": "failed"}).json()
    assert {run["ticket_id"] for run in failed} == {"t-1"}
    assert len(failed) == 3
    assert [
        r["ticket_id"] for r in client.get("/internal/runs?ticket_id=t-2").json()
    ] == ["t-2"]
    assert len(client.get("/internal/runs", params={"limit": 2}).json()) == 2
    assert len(client.get("/internal/runs", params={"offset": 3}).json()) == 1


@pytest.mark.parametrize(
    "params",
    [{"status": "pending"}, {"limit": 0}, {"limit": 101}, {"offset": -1}],
)
def test_runs_rejects_invalid_query(client: TestClient, params: dict) -> None:
    assert client.get("/internal/runs", params=params).status_code == 422


def test_runs_are_not_part_of_the_public_api(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()

    assert not [path for path in spec["paths"] if "runs" in path]
    assert client.get("/runs").status_code == 404
