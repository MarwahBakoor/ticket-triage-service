import sqlite3
from pathlib import Path

import pytest

from app.db.connection import get_connection


def test_committed_data_persists_across_connections(database_path: Path) -> None:
    with get_connection() as connection:
        connection.execute("CREATE TABLE example (id TEXT PRIMARY KEY, body TEXT)")
        connection.execute(
            "INSERT INTO example (id, body) VALUES (?, ?)",
            ("one", "A customer's request"),
        )

    assert database_path.is_file()
    with get_connection() as connection:
        row = connection.execute(
            "SELECT body FROM example WHERE id = ?", ("one",)
        ).fetchone()
    assert isinstance(row, sqlite3.Row)
    assert row["body"] == "A customer's request"


def test_failed_transaction_rolls_back() -> None:
    with get_connection() as connection:
        connection.execute("CREATE TABLE example (id TEXT PRIMARY KEY)")

    with pytest.raises(sqlite3.IntegrityError), get_connection() as connection:
        connection.execute("INSERT INTO example (id) VALUES (?)", ("one",))
        connection.execute("INSERT INTO example (id) VALUES (?)", ("one",))

    with get_connection() as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM example").fetchone()
        assert row["count"] == 0


def test_default_database_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_PATH")
    monkeypatch.chdir(tmp_path)

    with get_connection() as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            == []
        )

    assert (tmp_path / "tickets.db").is_file()
