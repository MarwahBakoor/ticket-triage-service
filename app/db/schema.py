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
                    CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
