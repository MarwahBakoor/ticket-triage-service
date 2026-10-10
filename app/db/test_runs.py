from pathlib import Path

import pytest

from app.db.connection import get_connection
from app.db.runs import count_runs_by_status, list_runs
from app.db.schema import initialize_database


@pytest.fixture(autouse=True)
def initialized_database(database_path: Path) -> None:
    initialize_database()


def add_run(
    run_id: int, ticket_id: str, run_number: int, status: str, started_at: str
) -> None:
    finished_at = None if status == "running" else started_at
    error = "timeout" if status == "failed" else None
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO classification_runs
                (id, ticket_id, run_number, status, error, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, ticket_id, run_number, status, error, started_at, finished_at),
        )


@pytest.fixture
def runs() -> None:
    add_run(1, "t-1", 1, "failed", "2026-10-10T10:00:00+00:00")
    add_run(2, "t-1", 2, "completed", "2026-10-10T10:01:00+00:00")
    add_run(3, "t-2", 1, "running", "2026-10-10T10:02:00+00:00")
    add_run(4, "t-3", 1, "failed", "2026-10-10T10:03:00+00:00")


def ids(runs: list[dict]) -> list[int]:
    return [run["id"] for run in runs]


def test_list_runs_returns_newest_first(runs):
    assert ids(list_runs()) == [4, 3, 2, 1]


def test_list_runs_returns_run_fields(runs):
    run = list_runs(ticket_id="t-1", status="failed")[0]

    assert run == {
        "id": 1,
        "ticket_id": "t-1",
        "run_number": 1,
        "status": "failed",
        "error": "timeout",
        "started_at": "2026-10-10T10:00:00+00:00",
        "finished_at": "2026-10-10T10:00:00+00:00",
    }


def test_list_runs_filters_by_status(runs):
    assert ids(list_runs(status="failed")) == [4, 1]


def test_list_runs_filters_by_ticket(runs):
    assert ids(list_runs(ticket_id="t-1")) == [2, 1]


def test_list_runs_applies_limit_and_offset(runs):
    assert ids(list_runs(limit=2, offset=1)) == [3, 2]


def test_count_runs_by_status(runs):
    assert count_runs_by_status() == {"running": 1, "completed": 1, "failed": 2}


def test_count_runs_by_status_includes_zero_counts():
    assert count_runs_by_status() == {"running": 0, "completed": 0, "failed": 0}
