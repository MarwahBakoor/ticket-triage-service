import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on failure, and always close the connection."""
    connection = sqlite3.connect(os.environ.get("DATABASE_PATH", "tickets.db"))
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection
    finally:
        connection.close()
