import sqlite3
from pathlib import Path

import pytest

from app.database import get_connection


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
    assert row == ("A customer's request",)


def test_failed_transaction_rolls_back() -> None:
    with get_connection() as connection:
        connection.execute("CREATE TABLE example (id TEXT PRIMARY KEY)")

    with pytest.raises(sqlite3.IntegrityError), get_connection() as connection:
        connection.execute("INSERT INTO example (id) VALUES (?)", ("one",))
        connection.execute("INSERT INTO example (id) VALUES (?)", ("one",))

    with get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM example").fetchone() == (0,)
