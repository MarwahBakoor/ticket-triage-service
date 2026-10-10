# Ticket Triage Service

An HTTP service that ingests support tickets and classifies each one in the
background with an LLM:

- a **category**: billing, technical, account or other
- a **priority**: low, medium or high
- a one-sentence **summary**

The model is treated as an unreliable dependency that returns text: its output
is validated before anything is stored, and failures are retried, then
recorded. No real model is wired in; a keyword-based fake stands in for one
and sometimes returns broken output on purpose.

## Contents

1. [Quick start](#quick-start)
2. [Using it](#using-it)
3. [Decisions](#decisions)
4. [Weaknesses](#weaknesses)
5. [With more time](#with-more-time)
6. [Development](#development)

## Quick start

You need **Python 3.12+** and **[uv](https://docs.astral.sh/uv/getting-started/installation/)**.

```sh
git clone https://github.com/MarwahBakoor/ticket-triage-service.git
cd ticket-triage-service
uv sync
uv run uvicorn app.main:app
```

Then, in a second terminal, load the ten sample tickets from the brief:

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

Every endpoint, status code and error is described in
[docs/API.md](docs/API.md).

The **dashboard** shows the ticket list with filters, each ticket's details
(with a **Reclassify** button once it is classified or failed), and a Metrics
tab with every classification attempt ("run") and its error. It updates live.

| Setting | Default | What it does |
| --- | --- | --- |
| `DATABASE_PATH` | `tickets.db` | The SQLite file tickets are saved in. |
| `CLASSIFICATION_WORKERS` | `4` | How many tickets are classified at once. |

## Decisions

### Ticket lifecycle

`pending` → `processing` → `classified` or `failed`. The brief names
`pending`, `classified` and `failed`. I added `processing` so that on restart
the service can tell work that was interrupted from work that never started.
A `failed` ticket keeps null classification fields, and each failed attempt's
error is recorded as fixed text.

### Storage: SQLite

I used Python's built-in `sqlite3` with three tables:

- `tickets` holds the content and the latest *validated* result.
- `classification_jobs` holds the current status and attempt count, one row
  per ticket. It is what a worker claims.
- `classification_runs` records every attempt and its error, as history.

Why: no setup, and transactions make the important steps atomic. A ticket
and its pending job are created together. A valid result and the
`classified` status are stored together. `CHECK` constraints repeat the
allowed categories, priorities and statuses, so a bug in application code
still cannot store an invalid value.

The cost: one writer at a time, and the data lives on one machine.

### Duplicates

`INSERT … ON CONFLICT (id) DO NOTHING`. Only the request that actually
inserted the ticket queues it. A repeat submission returns the stored ticket
unchanged with `202`, ignores the new subject and body, and does not
classify again. This holds for concurrent duplicates too, and there is a test
for it.

### Async execution: an in-process queue

`POST /tickets` only writes to the database. After the commit, the ticket id
goes onto an `asyncio.Queue` that worker tasks consume. The database is the
source of truth and the queue is only a cache of work to do, so losing the
queue loses nothing.

Why: no broker or extra process to run.

The cost: only one service process may use a database. See
[Weaknesses](#weaknesses).

### Concurrency

There is a fixed pool of `CLASSIFICATION_WORKERS` tasks, 4 by default, and
each handles one ticket at a time. A fixed pool is the simplest way to stay
under a provider's rate limits and to bound cost. Database calls run in a
thread so they never block the event loop.

### Restart

On startup, before any worker runs:

- jobs left in `processing` go back to `pending`;
- their unfinished runs are recorded as failed;
- every `pending` job is queued again, oldest first.

The attempt count is kept, so a ticket can't escape the retry limit by
crashing the service. The interrupted attempt itself is not counted against
it. On shutdown, workers are cancelled and in-flight tickets resume on the
next start.

The trade-off: a model call can happen twice for one attempt. That is
at-least-once processing, never lost work.

### Retries and failure

Each ticket gets 3 attempts. Each of these counts as a failed attempt:

- a provider error;
- no answer within 30 seconds (so a hung call can't hold a worker forever);
- text that isn't JSON;
- an unknown category or priority;
- a bad summary;
- extra fields.

Retries wait 1 s, then 2 s. After the third failure the ticket is `failed`.

`POST /tickets/{id}/reclassify` (the optional extra I picked) gives a
`classified` or `failed` ticket a fresh set of attempts, for example after
an outage or a prompt change. It clears the old result in the same
transaction, so a ticket never shows a stale answer. A ticket that is still
in progress returns `409`, so the endpoint can't queue a ticket twice.

### Model output validation

The path is raw text → strict Pydantic model → database. Only a validated
`ClassificationResult` can reach the function that stores a result. The
model rejects:

- categories and priorities outside the allowed sets, including wrong case;
- missing or extra fields;
- non-string summaries;
- summaries that are empty, longer than 300 characters, or more than one
  line.

"One sentence" is requested in the prompt but not parsed, because
abbreviations like "e.g." would make good answers fail. Raw output and
exception messages are never stored. Errors are fixed strings such as
`Model output was not a valid classification`.

### Prompt injection

The ticket goes into the prompt as JSON inside `<ticket>` tags, with `<`
escaped so it can't close the tag. The instructions say it is data and must
not be obeyed. That reduces the risk but does not prevent injection.

The real boundary is validation: an injected ticket cannot get a disallowed
value stored. It *can* steer the model to a wrong but allowed answer.
Sample t-1005 shows this, and tests cover both cases. The fake rates t-1005
`high` because it says "URGENT", and a real model might write its requested
summary. The summary is model text, so the dashboard only ever inserts it as
text, never as HTML.

### API shape

- Plain JSON over REST.
- `202` for submit and reclassify, because the work happens later.
- `404` for an unknown id, `409` for reclassifying a ticket in progress, and
  `422` for invalid input, all in FastAPI's `{"detail": …}` format.
- Lists use `limit`/`offset` paging, with filters that combine with AND.

## Weaknesses

- **No real model.** The keyword fake is plausible, not accurate. Latency,
  rate limits and output drift from a real provider are untested.
- **One process per database.** Startup recovery assumes no other process is
  working on jobs. A second instance would reset the first one's work.
- **Model calls are at-least-once.** A crash or shutdown mid-call repeats that
  call on restart, which a real provider would charge for twice.
- **Shutdown isn't graceful.** In-flight attempts are cancelled and redone
  rather than allowed to finish.
- **Every error is retried**, including ones that can't succeed (such as a bad
  API key), and a worker stays busy while it waits to retry.
- **Injection can still steer allowed values**, including the summary text.
- **No migrations.** A schema change means deleting the database. The service
  refuses to start on a database from before the `classified` rename and says
  so.
- **No authentication.** The dashboard's `/internal/runs` endpoints are only
  hidden from the API docs, not protected.
- **Paging** returns no total, and `order=newest` can repeat a ticket while new
  ones arrive.
- **The dashboard** is more than the brief asked for, and its metrics view reads
  every ticket rather than using a stats endpoint.

## With more time

- A real provider behind the `LLMClient` interface, with errors that can't
  succeed on retry failing immediately instead of being retried.
- Graceful shutdown: stop taking new tickets and let in-flight attempts finish.
- Record the prompt and model version with each result, so a prompt change
  reclassifies only the tickets it affects.
- A small labelled evaluation set and a script that reports agreement.
- Postgres with lease-based job claims (`FOR UPDATE SKIP LOCKED`) to run more
  than one process.
- Cursor pagination, authentication, and a stats endpoint for the dashboard.

## Development

```sh
uv run pytest                 # tests
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
```

Tests sit next to the code they cover (`app/**/test_*.py`). Each one uses a
temporary SQLite database and a scripted fake LLM, never `tickets.db` or a live
model.

```text
app/
├── main.py             App wiring: lifespan, workers, dashboard
├── api/                HTTP routes and request/response models
├── db/                 Schema and parameterized SQL
├── llm/                Client interface, fakes, prompt, output validation
├── classification/     One ticket's classification, with retries
└── workers/            Queue and worker pool
frontend/               Dashboard (plain HTML/CSS/JS, no build step)
sample_data/            The brief's ten sample tickets
scripts/load_samples.py Loads them into a running service
docs/                   API reference and design notes
```

If the service won't start because port 8000 is taken, add `--port 8001` and
pass `http://127.0.0.1:8001` to `load_samples.py`. To start over, stop the
service and delete `tickets.db`.

More detail: [docs/API.md](docs/API.md) for the API,
[docs/DESIGN.md](docs/DESIGN.md) for the design, and
[AGENTS.md](AGENTS.md) for contributor conventions.
