# Design notes

How the ticket-triage service works and why. For running and using it, see
[README.md](../README.md); for the API, see [API.md](API.md).

## Data model

- `tickets`: the ticket content plus the latest successful `category`,
  `priority` and `summary`.
- `classification_jobs`: one row per ticket with the async status, `attempts`
  and `last_error`.
- `classification_runs`: one row per classification attempt, numbered per
  ticket (`run_number`), with its status (`running`, `completed` or `failed`),
  a fixed-text `error`, and `started_at`/`finished_at`. A CHECK constraint
  keeps `finished_at` null exactly while a run is `running`.

Operational state lives apart from the ticket so that the ticket only holds
validated results. Retries, errors and status transitions change the job row
without touching ticket data, and a validated result plus the `completed`
status are written in one transaction. Each run is finished in the same
transaction as the job change it causes, so runs and jobs always agree.
Both CHECK constraints and the
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
- runs still `running` are marked `failed` with the error
  `Interrupted before finishing`. They don't use up an attempt.
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
- **Fake LLM**: the keyword fake is plausible, not accurate. For example, it
  rates `t-1005` high priority because the text says "URGENT". Behavior against
  a real provider (latency, rate limits, output drift) is untested.
- Classification status is named `completed` rather than `classified`.
- Database calls in the classification workflow run on the event loop. They
  are short, but a locked database would briefly block the loop.

## With more time

- Add a real provider client behind `LLMClient`, chosen by configuration, with
  timeouts and rate-limit handling.
- Exponential backoff between retries.
- Graceful shutdown that lets in-flight attempts finish before cancelling.
- A way to re-run failed jobs or re-classify after a prompt change.
- Record the prompt/model version with each classification.
- A small labelled evaluation set to measure classifier agreement.
- Move to Postgres with a lease-based job claim if more than one process is
  needed.

## Internal endpoints

The dashboard's metrics view reads runs from `GET /internal/runs` and
`GET /internal/runs/summary`. They are deliberately not part of the public
API: they are left out of the OpenAPI schema and `API.md`, and may change
without notice. The service has no authentication, so this keeps them out of
the public contract rather than protecting them; in production they would sit
behind auth or on an internal network.

## Dashboard

The dashboard in `frontend/` is plain HTML, CSS and JavaScript with no build
step, served by FastAPI from the same origin as the API, so it needs no CORS
setup. Ticket text is untrusted, so the dashboard only ever inserts it as text,
never as HTML. The API has no stats endpoint, so the metrics view reads every
ticket in pages of 100 (capped at 2,000). That is fine at this scale but should
become a dedicated endpoint for real volumes.

## Testing approach

Tests are co-located with the code they cover. They use temporary SQLite files
and scripted fake LLMs (installed via `app.state.llm_client`); they never touch
`tickets.db` or a live model.
