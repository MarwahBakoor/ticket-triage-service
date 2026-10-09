# Ticket-triage service

A FastAPI service that ingests support tickets, classifies them asynchronously
with an LLM, validates the model output, and serves the results.

## Running

Prerequisites: Python 3.12+ and [uv](https://docs.astral.sh/uv/). SQLite ships
with Python.

```sh
uv sync
uv run uvicorn app.main:app --reload
curl http://127.0.0.1:8000/health
```

The database is `tickets.db` in the current directory, created on startup. To
use another file:

```sh
export DATABASE_PATH=/path/to/tickets.db
```

Classification concurrency is set with `CLASSIFICATION_WORKERS` (default `4`).

Load the ten sample tickets (`t-1001`–`t-1010`) into a running service:

```sh
uv run python scripts/load_samples.py                     # http://127.0.0.1:8000
uv run python scripts/load_samples.py http://host:port
```

The loader posts each ticket through `POST /tickets`, so rerunning it is safe.

**Note:** no real LLM client is wired into `app.main` yet. Without one, the
service logs a warning, starts no workers, and new tickets stay `pending`.
Tests inject deterministic fakes from `app/llm/fake.py` via
`app.state.llm_client`.

Tests and lint:

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Tests use temporary SQLite files and fake LLMs; they never touch `tickets.db`
or a live model.

## API

| Method | Path            | Result                                                      |
| ------ | --------------- | ----------------------------------------------------------- |
| POST   | `/tickets`      | `202` with the stored ticket; `422` on invalid input        |
| GET    | `/tickets/{id}` | `200` with the ticket; `404` if unknown                     |
| GET    | `/tickets`      | `200` with a list, oldest first; `422` on invalid query     |

`POST /tickets` takes `{"id", "subject", "body"}`. `id` and `body` must be
non-empty; `subject` is required but may be empty. Resubmitting an existing id
returns the stored ticket unchanged and does not classify it again.

Every ticket response includes `category`, `priority` and `summary` (null until
classified) and `classification_status`: `pending`, `processing`, `completed`
or `failed`.

Filtering and pagination on `GET /tickets`:

- `category`: `billing`, `technical`, `account` or `other`
- `priority`: `low`, `medium` or `high`
- `limit`: 1–100, default 20
- `offset`: ≥ 0, default 0

```sh
curl "http://127.0.0.1:8000/tickets?category=billing&priority=high&limit=10&offset=0"
```

## Data model

- `tickets`: the ticket content plus the latest successful `category`,
  `priority` and `summary`.
- `classification_jobs`: one row per ticket with the async status, `attempts`
  and `last_error`.

Operational state lives apart from the ticket so that the ticket only holds
validated results. Retries, errors and status transitions change the job row
without touching ticket data, and a validated result plus the `completed`
status are written in one transaction. Both CHECK constraints and the
application restrict the allowed values. There are no foreign keys; the
relationship is enforced in application code.

## Async execution

`POST /tickets` stores the ticket and its `pending` job in one transaction. Only
when the ticket is new, and after that commit, is its id put on an in-process
`asyncio.Queue`. Classification never runs inside the request.

The FastAPI lifespan starts `CLASSIFICATION_WORKERS` worker tasks. Each handles
one ticket at a time, so no more than that many classifications run at once.
Each database operation opens and closes its own short-lived connection.

## Restart behavior

SQLite is the durable source of truth; the queue is only a cache of work to do.
On startup, before workers run:

- jobs still `processing` are reset to `pending`. With an in-process queue, a
  job in that state at startup was owned by a process that stopped
  mid-attempt. Its attempt count is kept, so the retry limit still applies.
- every `pending` job is enqueued, oldest first.
- `completed` and `failed` jobs are never enqueued.

On shutdown, workers are cancelled. Interrupted jobs stay `processing` and are
recovered on the next start.

## Retry policy

Each job gets at most 3 attempts. Provider exceptions, malformed JSON and
validation failures all count as failed attempts and are retried. After the
third failure the job becomes `failed` and the ticket's classification fields
stay null. `last_error` holds fixed text such as
`LLM call failed: TimeoutError`, never raw model output or exception messages.

## LLM trust boundary

Model output is untrusted text:

```text
raw text -> JSON parse -> Pydantic validation -> persistence
```

`parse_classification` validates with a strict Pydantic model: exact allowed
`category` and `priority` values, a non-empty `summary`, no extra fields. Only
a validated `ClassificationResult` can reach `complete_classification`. Raw
output is never stored.

## Prompt injection

Ticket subject and body come from the public. The prompt marks them as untrusted
data, tells the model not to follow instructions inside them, and places them as
JSON inside `<ticket>` tags, escaping `<` so ticket text cannot close the tag.

That reduces the risk but does not prevent injection. The real application
boundary is output validation: an injected ticket can never cause a
disallowed value to be stored. It can still steer the model toward a wrong but
allowed answer. Sample `t-1005` is a regression test covering both cases.

## Trade-offs

- **SQLite**: zero setup and transactional, but one writer at a time and
  local to one machine.
- **In-process queue**: simple and dependency-free, but tied to one process.
  Running several service processes against one database is unsafe, because
  startup recovery would reset jobs another process is working on.
- **No durable external job system**: durability comes from the
  `classification_jobs` table, not the queue. A crash loses only in-flight
  attempts, which are retried on restart.
- **No migrations**: `CREATE TABLE IF NOT EXISTS` only. Schema changes on an
  existing database need manual handling.
- **Fake LLM**: only deterministic fakes exist, and none is wired into the
  running app yet. Behavior against a real provider (latency, rate limits,
  output drift) is untested.
- Classification status is named `completed` rather than `classified`.
- Database calls in the classification workflow run on the event loop. They
  are short, but a locked database would briefly block the loop.

## With more time

- Wire a real provider client behind `LLMClient`, with timeouts and rate-limit
  handling.
- Exponential backoff between retries.
- Graceful shutdown that lets in-flight attempts finish before cancelling.
- A way to re-run failed jobs or re-classify after a prompt change.
- Record the prompt/model version with each classification.
- A small labelled evaluation set to measure classifier agreement.
- Move to Postgres with a lease-based job claim if more than one process is
  needed.
