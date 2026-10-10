from pathlib import Path

import pytest

from app import constants
from app.main import app


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
