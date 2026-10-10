# Ticket Triage Service

An HTTP service that ingests support tickets and classifies each one in the
background with an LLM.

## Contents

1. [Quick start](#quick-start)
2. [Using it](#using-it)
3. [How it works](#how-it-works)
4. [Development](#development)

## Quick start

You need **Python 3.12+** and **[uv](https://docs.astral.sh/uv/getting-started/installation/)**.

```sh
git clone https://github.com/MarwahBakoor/ticket-triage-service.git
cd ticket-triage-service
uv sync
uv run uvicorn app.main:app
```

Then, in a second terminal, load ten sample tickets:

```sh
uv run python scripts/load_samples.py
```

Open <http://127.0.0.1:8000/> for the dashboard, or
<http://127.0.0.1:8000/docs> for the interactive API reference. The samples
are classified within a few seconds. Running the loader again is safe.

## Using it

```sh
# Submit a ticket: 202, classification_status "pending"
curl -X POST http://127.0.0.1:8000/tickets \
  -H 'Content-Type: application/json' \
  -d '{"id": "t-2001", "subject": "API returning 500s", "body": "Every export call fails since 09:00."}'

# Read it back until classification_status is "classified" or "failed"
curl http://127.0.0.1:8000/tickets/t-2001

# List, filtered and paged
curl "http://127.0.0.1:8000/tickets?category=technical&priority=high&limit=10&offset=0"

# Classify a finished ticket again, e.g. one that failed
curl -X POST http://127.0.0.1:8000/tickets/t-2001/reclassify
```

Every endpoint, parameter and status code is listed at
<http://127.0.0.1:8000/docs>, where you can also try them out.

## How it works

### Ticket lifecycle

`pending` → `processing` → `classified` or `failed`.

- **`pending`**: stored and waiting for a worker.
- **`processing`**: a worker has claimed the ticket and is classifying it.
  Finding and claiming the next ticket is a single `UPDATE … RETURNING`, so
  two workers can never claim the same ticket.
- **`classified`**: a validated category, priority and summary are stored.
- **`failed`**: no valid classification after 3 attempts. The classification
  fields stay null, and each failed attempt's error is recorded as fixed text.

### Storage

Tickets are stored in SQLite through Python's built-in `sqlite3`, in three
tables:

- `tickets` holds the content and the latest _validated_ result.
- `classification_jobs` holds the current status and attempt count, one row
  per ticket. It is the row a worker claims.
- `classification_runs` records every attempt and its error, as history.

SQLite needs no setup, and its transactions keep the important steps atomic.

### Background classification

`POST /tickets` saves the ticket as `pending`, so classification never
runs inside the request.
The database is the queue: workers poll it, claim the ticket that has waited longest, and classify it. When nothing is pending,
a worker sleeps for a second before asking again, so a new ticket is picked up
within about a second.

### Concurrency

A fixed pool of `CLASSIFICATION_WORKERS` tasks (4 by default) classifies tickets, each handling one ticket at a time.

### Restarts

On startup, before any worker runs:

- jobs left in `processing` go back to `pending`, where workers find them;
- their unfinished runs are recorded as failed.

### Retries and failure

Each ticket gets 3 attempts. Each of these counts as a failed attempt:

- a provider error;
- no answer within 30 seconds, so a hung call can't hold a worker forever;
- text that isn't JSON;
- an unknown category or priority;
- a bad summary;
- extra fields.

Retries wait 1 s, then 2 s. After the third failure the ticket is `failed`.

`POST /tickets/{id}/reclassify` gives a `classified` or `failed` ticket a fresh
set of attempts, for example after an outage or a prompt change. It also
appears as a button in the dashboard's ticket view. It clears the old result
in the same transaction, so a ticket never shows a stale answer.

### The model

No real provider is connected. A keyword-based stand-in
(`app/llm/keyword.py`) classifies tickets so the service is usable, and every
4th call returns broken output on purpose (malformed JSON, an unknown
category or priority, or JSON wrapped in prose), so retries happen in normal
use. A real provider would replace it by implementing the same `LLMClient`
interface.

## Development

```sh
uv run pytest                 # tests
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
```

```text
app/
├── main.py             App wiring: lifespan, workers, dashboard
├── constants.py        Tunable values: attempts, timeout, retry delay, limits
├── labels.py           Allowed categories and priorities
├── api/                HTTP routes and request/response models
├── db/                 Schema and parameterized SQL
├── llm/                Client interface, keyword stand-in model, prompt,
│                       output validation; fake.py holds test doubles
├── classification/     One ticket's classification, with retries
└── workers/            Worker pool that polls for pending tickets
frontend/               Dashboard (plain HTML/CSS/JS, no build step)
sample_data/            Ten sample tickets
scripts/load_samples.py Loads them into a running service
```
