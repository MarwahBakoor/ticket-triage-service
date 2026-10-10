# Ticket Triage API

Submit support tickets, then read them back once a background worker has
classified them with an LLM.

- Interactive reference (generated from the code): `/docs` (Swagger UI) and
  `/redoc`, schema at `/openapi.json`.
- This page explains behavior the schema can't show: the asynchronous
  lifecycle, idempotency, failures, pagination and ordering.

## Contents

- [Quick start](#quick-start)
- [Conventions](#conventions)
- [The ticket object](#the-ticket-object)
- [Classification lifecycle](#classification-lifecycle)
- [Endpoints](#endpoints): [Submit](#submit-a-ticket) ·
  [Get](#get-a-ticket) · [List](#list-tickets) ·
  [Reclassify](#reclassify-a-ticket) · [Health](#health-check)
- [Pagination and ordering](#pagination-and-ordering)
- [Errors](#errors)
- [Limitations](#limitations)

## Quick start

```sh
# 1. Submit a ticket. The response comes back before it is classified.
curl -s -X POST http://127.0.0.1:8000/tickets \
  -H 'Content-Type: application/json' \
  -d '{"id": "t-2001", "subject": "API returning 500s", "body": "Every export call fails since 09:00."}'
# → 202, "classification_status": "pending", category/priority/summary null

# 2. Poll until the status is classified or failed.
curl -s http://127.0.0.1:8000/tickets/t-2001
# → 200, "classification_status": "classified", "category": "technical", ...

# 3. List the most urgent work first.
curl -s 'http://127.0.0.1:8000/tickets?order=priority&limit=10'
```

## Conventions

| | |
| --- | --- |
| Base URL | `http://127.0.0.1:8000` when run locally |
| Format | JSON request and response bodies, UTF-8 |
| Timestamps | ISO 8601 in UTC, e.g. `2026-10-10T11:08:58.961142Z` |
| Authentication | None. Do not expose the service publicly as it stands. |
| Errors | `{"detail": ...}`, see [Errors](#errors) |

## The ticket object

Every ticket endpoint returns this shape.

```json
{
  "id": "t-1001",
  "subject": "Charged twice this month",
  "body": "Hi, I see two charges of 49.00 on my card statement dated the 3rd and the 4th. I only have one subscription. Can you refund one of them?",
  "category": "billing",
  "priority": "medium",
  "summary": "Customer wrote in about: Charged twice this month.",
  "created_at": "2026-10-10T11:08:58.961142Z",
  "updated_at": "2026-10-10T11:08:58.962843Z",
  "classification_status": "classified"
}
```

| Field | Type | Description |
| --- | --- | --- |
| `id` | string | Chosen by the client when submitting. Unique. |
| `subject` | string | May be an empty string. |
| `body` | string | The customer's message. |
| `category` | string or null | `billing`, `technical`, `account` or `other`. Null until classified, and stays null if classification fails. |
| `priority` | string or null | `low`, `medium` or `high`. Null until classified, and stays null if classification fails. |
| `summary` | string or null | One sentence written by the model, at most 300 characters on a single line. Null until classified. |
| `created_at` | timestamp | When the ticket was first submitted. |
| `updated_at` | timestamp | When the ticket last changed, e.g. when its classification was stored. |
| `classification_status` | string | `pending`, `processing`, `classified` or `failed`. See below. |

`category` and `priority` are always one of the listed values: model output is
validated before anything is stored. `summary` is the model's own wording, so
treat it as untrusted text when displaying it.

## Classification lifecycle

```text
POST /tickets ──► pending ──► processing ──► classified
                     ▲             │
                     │             └───────► failed   (after 3 failed attempts)
                     │
                     └── POST /tickets/{id}/reclassify   (from classified or failed)
```

| Status | Meaning |
| --- | --- |
| `pending` | Stored and waiting for a worker. |
| `processing` | A worker is classifying it now. |
| `classified` | `category`, `priority` and `summary` are set. |
| `failed` | No valid classification after 3 attempts. The classification fields stay null. |

- Classification usually finishes within moments. Poll `GET /tickets/{id}`
  every second or two until the status is `classified` or `failed`. The
  dashboard polls every 1.5 s while anything is in progress.
- An attempt fails if the model call errors, takes longer than 30 seconds,
  returns text that isn't JSON, or returns values outside the allowed sets.
  Failed attempts are retried after 1 s, then 2 s, up to 3 attempts in total.
- `classified` and `failed` stay put unless you
  [reclassify](#reclassify-a-ticket) the ticket.
- If the service restarts mid-classification, the ticket goes back to
  `pending` and is picked up again on startup. Attempts already used still
  count towards the limit.

## Endpoints

### Submit a ticket

`POST /tickets`

Stores the ticket and queues it for classification, then returns
**`202 Accepted`** without waiting for the classification.

**Request body**

| Field | Type | Rules |
| --- | --- | --- |
| `id` | string | Required, at least 1 character. |
| `subject` | string | Required, may be empty (`""`). |
| `body` | string | Required, at least 1 character. |

```sh
curl -s -X POST http://127.0.0.1:8000/tickets \
  -H 'Content-Type: application/json' \
  -d '{"id": "t-1001", "subject": "Charged twice this month", "body": "I see two charges of 49.00. Can you refund one?"}'
```

**Responses**

| Status | When |
| --- | --- |
| `202` | The ticket was stored, or already existed. Body: the ticket. |
| `422` | The body is missing a field, has the wrong type, or isn't valid JSON. |

**Idempotency.** Submitting is safe to retry. If a ticket with the same `id`
already exists, you get the **stored** ticket back with `202`:

- the new `subject` and `body` are ignored, and the original is not changed;
- it is not classified again;
- concurrent submissions with the same id still create exactly one ticket.

To tell a new ticket from an existing one, compare the returned `subject` and
`body` with what you sent, or check `created_at`.

### Get a ticket

`GET /tickets/{ticket_id}`

```sh
curl -s http://127.0.0.1:8000/tickets/t-1001
```

| Status | When |
| --- | --- |
| `200` | Body: the ticket. |
| `404` | No ticket has this id. Body: `{"detail": "Ticket not found"}` |

### List tickets

`GET /tickets`

Returns a JSON array of tickets, which may be empty.

| Query parameter | Values | Default | Description |
| --- | --- | --- | --- |
| `category` | `billing`, `technical`, `account`, `other` | none | Only tickets in this category. |
| `priority` | `low`, `medium`, `high` | none | Only tickets with this priority. |
| `order` | `oldest`, `newest`, `priority` | `oldest` | Sort order, see [below](#ordering). |
| `limit` | 1–100 | 20 | Maximum number of tickets to return. |
| `offset` | ≥ 0 | 0 | Number of tickets to skip. |

Filters combine with AND. They only match **classified** tickets: a ticket has
no category or priority while `pending` or `processing`, or after `failed`.

```sh
# High-priority billing tickets, newest first
curl -s 'http://127.0.0.1:8000/tickets?category=billing&priority=high&order=newest'

# Second page of 10
curl -s 'http://127.0.0.1:8000/tickets?limit=10&offset=10'
```

| Status | When |
| --- | --- |
| `200` | Body: an array of tickets. |
| `422` | A query parameter has an unknown value or is out of range. |

### Reclassify a ticket

`POST /tickets/{ticket_id}/reclassify`

Queues a `classified` or `failed` ticket for a fresh classification, for
example after a model outage or a prompt change. Returns **`202 Accepted`**
straight away. The previous result is cleared (`category`, `priority` and
`summary` become null), the ticket gets a new set of 3 attempts, and the
attempts from before are kept in its run history.

```sh
curl -s -X POST http://127.0.0.1:8000/tickets/t-1001/reclassify
```

| Status | When |
| --- | --- |
| `202` | Queued. Body: the ticket, now `pending`. |
| `404` | No ticket has this id. Body: `{"detail": "Ticket not found"}` |
| `409` | The ticket is still `pending` or `processing`. Body: `{"detail": "Ticket is still being classified"}` |

Because only a finished ticket can be reset, repeating or racing this request
never queues a ticket twice: the first wins and the rest get `409`.

### Health check

`GET /health` → `200 {"status": "ok"}` while the process is serving requests.
It does not check the database or the model.

### Other routes

| Route | What it is |
| --- | --- |
| `GET /` | Redirects (`307`) to the dashboard at `/app/`. |
| `GET /app/` | The web dashboard. |
| `GET /docs`, `GET /redoc` | Interactive API reference. |
| `GET /openapi.json` | OpenAPI schema. |

## Pagination and ordering

### Paging

Pagination uses `limit` and `offset`. Responses don't include a total or a
next-page link. Keep requesting `offset + limit` until a page returns fewer than
`limit` tickets:

```python
import json
import urllib.request

BASE_URL = "http://127.0.0.1:8000"
LIMIT = 100


def all_tickets():
    offset = 0
    while True:
        url = f"{BASE_URL}/tickets?order=oldest&limit={LIMIT}&offset={offset}"
        with urllib.request.urlopen(url) as response:
            page = json.load(response)
        yield from page
        if len(page) < LIMIT:
            return
        offset += LIMIT


tickets = {ticket["id"]: ticket for ticket in all_tickets()}  # de-duplicated by id
```

### Ordering

| `order` | Sort |
| --- | --- |
| `oldest` (default) | Submission time, oldest first. |
| `newest` | Submission time, newest first. |
| `priority` | `high`, then `medium`, `low`, then unclassified tickets. Oldest first within each group. |

Tickets submitted at the same instant are ordered by `id`, so the order is
always fully determined.

### Consistency while paging

Offsets count positions, so a page can shift when tickets are added or change
between requests:

| `order` | Effect of changes while you page |
| --- | --- |
| `oldest` | Stable. New tickets are added at the end, so earlier pages don't move. |
| `newest` | Each new ticket pushes everything down by one, so the next page can repeat a ticket you already saw. |
| `priority` | A ticket moves when its classification finishes, so it can be repeated or skipped. |

For a complete, stable export, page with `order=oldest` and de-duplicate by
`id`. Cursor-based pagination would remove repeats for `newest`. It is not
implemented because offset paging is accurate enough at this scale.

## Errors

Errors use FastAPI's standard shape: a JSON object with a `detail` field.

**404**: unknown ticket:

```json
{ "detail": "Ticket not found" }
```

**409**: reclassifying a ticket that is still being classified:

```json
{ "detail": "Ticket is still being classified" }
```

**422**: invalid input. `detail` lists every problem found. `loc` says where
the problem is (`body` or `query`, then the field):

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "id"],
      "msg": "String should have at least 1 character",
      "input": "",
      "ctx": { "min_length": 1 }
    },
    {
      "type": "missing",
      "loc": ["body", "body"],
      "msg": "Field required",
      "input": { "id": "", "subject": "x" }
    }
  ]
}
```

```json
{
  "detail": [
    {
      "type": "enum",
      "loc": ["query", "order"],
      "msg": "Input should be 'oldest', 'newest' or 'priority'",
      "input": "random",
      "ctx": { "expected": "'oldest', 'newest' or 'priority'" }
    }
  ]
}
```

A classification failure is **not** an HTTP error. It appears as
`classification_status: "failed"` on the ticket.

## Limitations

- No authentication or rate limiting.
- Tickets can't be edited or deleted through the API.
- No stats or count endpoint; list responses don't include a total.
- Run one service process per database: workers and startup recovery assume
  they are the only process using it.
- The running service uses a keyword-based fake classifier, not a real model.
  Every 4th call deliberately returns broken output (malformed JSON, an
  unknown category or priority, or JSON wrapped in prose) so that retries
  happen.
