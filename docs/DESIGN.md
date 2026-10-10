# Design notes

How the ticket-triage service works and why. For running and using it, see
[README.md](../README.md); for the API, see [API.md](API.md).

## Data model

- `tickets`: the ticket content plus the latest successful `category`,
  `priority` and `summary`.
- `classification_jobs`: one row per ticket with the async status and
  `attempts`. It is the current state, and the row a worker claims.
- `classification_runs`: one row per classification attempt, numbered per
  ticket (`run_number`), with its status (`running`, `completed` or `failed`),
  a fixed-text `error`, and `started_at`/`finished_at`. A CHECK constraint
  keeps `finished_at` null exactly while a run is `running`. It is the
  append-only history, and the only place errors are kept.

Operational state lives apart from the ticket so that the ticket only holds
validated results. Retries, errors and status transitions change the job row
without touching ticket data, and a validated result plus the `classified`
status are written in one transaction. Each run is finished in the same
transaction as the job change it causes, so runs and jobs always agree.

Jobs and runs are deliberately separate tables: one row per ticket versus one
row per attempt. Merging them would make "current status" mean "the latest
run", which every list query would have to compute, and would take away the
single-row conditional `UPDATE` that lets exactly one worker claim a ticket.
The job's `attempts` overlaps with the run count, but deriving it would need
a marker for the last reclassification, so it stays a counter.

Both CHECK constraints and the
application restrict the allowed values. There are no foreign keys; the
relationship is enforced in application code.

## Async execution

`POST /tickets` stores the ticket and its `pending` job in one transaction and
returns. Classification never runs inside the request.

The `classification_jobs` table is the queue. The FastAPI lifespan starts
`CLASSIFICATION_WORKERS` worker tasks that poll it. Each worker:

1. claims the pending job that has waited longest (`claim_next_job`);
2. classifies that ticket, with retries;
3. asks again. When nothing is pending, it sleeps for `POLL_INTERVAL_SECONDS`
   (1 s) first.

Claiming is one statement, an `UPDATE … WHERE ticket_id = (SELECT … LIMIT 1)
RETURNING ticket_id`. SQLite takes its write lock before a write statement
reads anything, so concurrent workers never claim the same job. Waiting time
counts from the job's `updated_at`, so a recovered or reclassified ticket joins
the back of the line. An index on `(status, updated_at)` keeps the lookup
cheap.

Polling is preferred over an in-process `asyncio.Queue` fed by the request.
With such a queue, saving a ticket and queuing it are two steps, and a ticket
saved but not queued waits for the next startup. With polling the database is
the only record of work, so a saved ticket is always found. The cost is up to
one poll interval of latency and a small query per idle worker per second.

Each worker handles one ticket at a time, so no more than `CLASSIFICATION_WORKERS`
classifications run at once. Each database operation opens and closes its own
short-lived connection.

## Restart behavior

On startup, before workers run (`recover_interrupted_jobs`):

- jobs still `processing` are reset to `pending`, where workers find them. A
  job in that state at startup was owned by a process that stopped
  mid-attempt. Its attempt count is kept, so the retry limit still applies.
- runs still `running` are marked `failed` with the error
  `Interrupted before finishing`. They don't use up an attempt.

Pending jobs need nothing: workers find them by polling.

On shutdown, workers are cancelled. Interrupted jobs stay `processing` and are
recovered on the next start.

## Retry policy

Each job gets at most 3 attempts. Provider exceptions, calls that take longer
than 30 seconds, malformed JSON and validation failures all count as failed
attempts. Retries wait 1 s, then 2 s (exponential backoff), so a briefly
overloaded provider is not hit again at once; the worker stays busy while it
waits. After the third failure the job becomes `failed` and the ticket's
classification fields stay null. Each failed run's `error` holds fixed text
such as `LLM call failed: TimeoutError`, never raw model output or exception
messages.

## LLM trust boundary

Model output is untrusted text:

```text
raw text -> JSON parse -> Pydantic validation -> persistence
```

`parse_classification` validates with a strict Pydantic model: exact allowed
`category` and `priority` values, a non-empty single-line `summary` of at most
300 characters, no extra fields. "One sentence" is asked for in the prompt but
not parsed, because abbreviations such as "e.g." would turn good answers into
failures. Only
a validated `ClassificationResult` can reach `complete_classification`. Raw
output is never stored.

## Reclassification

`POST /tickets/{id}/reclassify` resets a `classified` or `failed` job to
`pending` with 0 attempts and clears the ticket's classification, in one
transaction; a worker then claims it on its next poll. Clearing keeps the rule that a ticket only
shows a result from its current job; a failed reclassification never leaves a
stale answer looking current. The reset only matches finished jobs, so a
repeated or concurrent request gets `409` and changes nothing. Run
history is kept, and new runs continue the ticket's numbering. The dashboard's
ticket popup offers a Reclassify button for classified and failed tickets.

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
- **Database polling**: no broker and no work can be missed, but a new ticket
  waits up to one poll interval, and idle workers query once a second.
- **One process per database**: the atomic claim would let several processes
  share the work, but startup recovery resets every `processing` job, including
  ones another live process is working on. Postgres with lease timeouts and
  `FOR UPDATE SKIP LOCKED` would remove that limit.
- **No durable external job system**: durability comes from the
  `classification_jobs` table. A crash loses only in-flight attempts, which
  are retried on restart.
- **No migrations**: `CREATE TABLE IF NOT EXISTS` only. Schema changes on an
  existing database need manual handling.
- **Stand-in LLM**: the keyword client (`app/llm/keyword.py`) is plausible,
  not accurate. For example, it
  rates `t-1005` high priority because the text says "URGENT". Behavior against
  a real provider (latency, rate limits, output drift) is untested.
- Every error is retried, including ones that cannot succeed on a retry
  (such as an invalid API key against a real provider).

## With more time

- Add a real provider client behind `LLMClient`, chosen by configuration, with
  timeouts and rate-limit handling.
- Graceful shutdown that lets in-flight attempts finish before cancelling.
- Record the prompt/model version with each classification, so a prompt
  change can reclassify only the tickets it affects.
- Reclassify many tickets at once, rather than one at a time.
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
