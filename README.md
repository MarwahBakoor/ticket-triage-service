# Ticket-triage service

Requires Python 3.12+, uv, and Docker Compose.

## Setup

```sh
uv sync
export POSTGRES_USER=triage
export POSTGRES_PASSWORD=local-development-only
export POSTGRES_DB=triage
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
docker compose up -d
```

## Run

```sh
uv run uvicorn app.main:app --reload
curl http://127.0.0.1:8000/health
```

## Test and lint

```sh
uv run pytest
uv run ruff format .
uv run ruff check .
```

## Stop PostgreSQL

```sh
docker compose down
```
