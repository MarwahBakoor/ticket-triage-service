# Ticket-triage service

Requires Python 3.12+ and uv. SQLite is included with Python.

## Setup

```sh
uv sync
```

The database connection uses `tickets.db` in the current directory by default.
The file is created on first connection. To choose another location:

```sh
export DATABASE_PATH=/path/to/tickets.db
```

## Run

```sh
uv run uvicorn app.main:app --reload
curl http://127.0.0.1:8000/health
```

## Test and lint

```sh
uv run pytest
uv run pytest app/db/test_connection.py
uv run ruff format .
uv run ruff check .
```

Tests use isolated temporary SQLite files and never use the development database.
