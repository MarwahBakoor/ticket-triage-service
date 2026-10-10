import sqlite3

from app.db.connection import get_connection


def initialize_database() -> None:
    """Create missing tables while preserving existing data."""
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                category TEXT NULL
                    CHECK (category IN ('billing', 'technical', 'account', 'other')),
                priority TEXT NULL CHECK (priority IN ('low', 'medium', 'high')),
                summary TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS classification_jobs (
                ticket_id TEXT PRIMARY KEY,
                status TEXT NOT NULL
                    CHECK (status IN ('pending', 'processing', 'classified', 'failed')),
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # One row per classification attempt. A run is running until it
        # finishes, and only finished runs have finished_at.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS classification_runs (
                id INTEGER PRIMARY KEY,
                ticket_id TEXT NOT NULL,
                run_number INTEGER NOT NULL CHECK (run_number >= 1),
                status TEXT NOT NULL
                    CHECK (status IN ('running', 'completed', 'failed')),
                error TEXT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NULL,
                UNIQUE (ticket_id, run_number),
                CHECK ((status = 'running') = (finished_at IS NULL))
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS classification_runs_by_status
            ON classification_runs (status, started_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS classification_runs_by_start
            ON classification_runs (started_at)
            """
        )
        _reject_outdated_jobs_table(connection)


def _reject_outdated_jobs_table(connection: sqlite3.Connection) -> None:
    # There are no migrations, and SQLite cannot alter a CHECK constraint. A
    # database created before `completed` became `classified` would fail on
    # the first classification, so fail at startup with a clear fix instead.
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("classification_jobs",),
    ).fetchone()
    if "'classified'" not in row["sql"]:
        raise RuntimeError(
            "The database was created by an older version of this service. "
            "Delete it (DATABASE_PATH, tickets.db by default) and restart."
        )
