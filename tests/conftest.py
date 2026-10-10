import asyncio
from pathlib import Path

import pytest

from app import constants
from app.db.connection import get_connection
from app.main import app

# Guards against a hung test; never part of the asserted behavior.
IDLE_TIMEOUT_SECONDS = 5


@pytest.fixture(autouse=True)
def database_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "test.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    return path


@pytest.fixture(autouse=True)
def no_default_llm_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start the app without workers unless a test installs its own LLM client."""
    monkeypatch.setattr(app.state, "llm_client", None)


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry immediately; tests that check the backoff set their own delay."""
    monkeypatch.setattr(constants, "RETRY_BASE_DELAY_SECONDS", 0.0)


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let idle workers find new tickets almost at once."""
    monkeypatch.setattr(constants, "POLL_INTERVAL_SECONDS", 0.005)


def _has_unfinished_jobs() -> bool:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM classification_jobs
                WHERE status IN ('pending', 'processing')
            )
            """
        ).fetchone()
    return bool(row[0])


async def wait_until_idle() -> None:
    """Wait until no ticket is pending or processing, failing after a timeout.

    The database is the queue, so this is the moment every submitted ticket
    has been classified or has failed.
    """

    async def poll() -> None:
        while await asyncio.to_thread(_has_unfinished_jobs):
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), IDLE_TIMEOUT_SECONDS)
