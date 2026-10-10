---
name: testing
description: Add or update tests for this FastAPI service using pytest, co-located test files, behavior-focused assertions, isolated SQLite databases, and deterministic fakes for external dependencies.
---

# Testing

Use this skill when adding, changing, or reviewing tests.

## Goals

Tests should be:

- behavior-focused
- deterministic
- isolated
- easy to find
- easy to run individually
- fast enough to run frequently

Prefer tests that would catch meaningful regressions.

## Test location

Prefer co-locating tests next to the code they cover.

Example:

```text
app/
├── api/
│   ├── tickets.py
│   └── test_tickets.py
├── db/
│   ├── connection.py
│   ├── tickets.py
│   ├── test_connection.py
│   └── test_tickets.py
├── llm/
│   ├── client.py
│   ├── fake.py
│   ├── keyword.py
│   ├── prompts.py
│   ├── test_fake.py
│   ├── test_keyword.py
│   └── test_prompts.py
└── workers/
    ├── classification.py
    └── test_classification.py
```

Shared test infrastructure may live in:

```text
tests/
└── conftest.py
```

Keep shared fixtures there only when they are reused across multiple areas.

Do not move tests into a central `tests/` directory unless there is a concrete reason.

## Pytest discovery

Use pytest naming conventions:

```text
test_*.py
```

Test functions should use:

```python
def test_expected_behavior(): ...
```

Use names that explain the behavior being verified.

Good:

```python
def test_duplicate_ticket_is_not_created_twice(): ...
```

Avoid:

```python
def test_ticket_1(): ...
```

## Test behavior, not implementation

Prefer testing:

```text
input
→ observable result
→ persisted state
```

over asserting private implementation details.

Prefer:

```python
response = client.post("/tickets", json=payload)

assert response.status_code == 202
assert response.json()["status"] == "pending"
```

over:

```python
mock_insert.assert_called_once()
```

Mock interactions only when the interaction itself is part of the contract.

## Arrange, Act, Assert

Keep tests easy to scan.

Use the logical structure:

```python
def test_example():
    # Arrange

    # Act

    # Assert
```

Comments are optional when the structure is already obvious.

Keep each test focused on one behavior.

## SQLite tests

Tests must never use the development database.

Use an isolated temporary SQLite database.

Prefer pytest's `tmp_path` fixture:

```python
def test_something(tmp_path):
    db_path = tmp_path / "test.db"
```

Each test or test group should receive its own isolated database unless sharing is intentional and safe.

Do not rely on:

```text
tickets.db
```

during tests.

Tests must be safe to run in any order.

## Database behavior

Use the real SQLite implementation when testing:

- SQL queries
- constraints
- idempotency
- filtering
- pagination
- state transitions
- persistence behavior

Do not mock SQLite when database behavior is part of what the test is meant to verify.

Use parameterized SQL in both application code and test helpers.

## Fixtures

Use pytest fixtures for reusable setup.

Good fixture candidates:

- temporary database path
- initialized database
- FastAPI client
- fake LLM
- application configuration

Keep fixtures small and explicit.

Avoid large fixture chains that hide important setup.

Prefer:

```python
def test_create_ticket(client): ...
```

over fixtures that silently create unrelated tickets or classifications.

## API tests

Use HTTP requests against the FastAPI application.

Test:

- status code
- response body
- relevant persistent state

Do not call route functions directly when testing HTTP behavior.

Example:

```python
def test_create_ticket(client, db):
    response = client.post(
        "/tickets",
        json={
            "id": "t-1",
            "subject": "Cannot log in",
            "body": "Password reset did not work",
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "pending"

    ticket = get_ticket(db, "t-1")
    assert ticket is not None
```

## Validation tests

Test invalid input at system boundaries.

Examples:

- missing ticket fields
- invalid category
- invalid priority
- malformed LLM JSON
- missing classification fields
- empty summary
- invalid pagination values

Invalid data must not enter trusted persistent state.

## LLM tests

Never call a live LLM in automated tests.

Use a deterministic fake.

The fake should support:

- valid JSON
- malformed JSON
- invalid category
- invalid priority
- missing fields
- raised exceptions

Test the actual boundary:

```text
raw model text
→ JSON parsing
→ validation
→ persistence or rejection
```

Do not construct a trusted `ClassificationResult` directly when testing raw model handling.

## Ticket lifecycle tests

Prioritize lifecycle behavior.

Cover:

```text
new ticket
→ pending
```

```text
pending
→ valid classification
→ classified
```

```text
pending
→ repeated failure
→ failed
```

Also cover:

- duplicate ingestion
- duplicate ingestion does not trigger duplicate classification
- malformed model output
- invalid category
- invalid priority
- retry exhaustion
- recovery of pending tickets on startup

## Idempotency tests

Verify:

```text
same ticket id submitted multiple times
→ one stored ticket
→ one classification job
```

Do not only verify response codes.

Also verify persistent state.

When practical, add a concurrent duplicate-submission test.

## Filtering and pagination

Test:

- no filters
- category only
- priority only
- category + priority
- limit
- offset

Use deliberately different ticket records so incorrect filtering is easy to detect.

## Prompt injection tests

Treat ticket subject and body as untrusted content.

Include the provided prompt-injection-style sample.

Verify:

- ticket content is placed inside the untrusted-data section of the prompt
- application instructions remain separate
- model output still goes through normal parsing and validation

Do not claim prompt injection can be fully prevented.

The important boundary is that untrusted model output cannot bypass validation.

## Async worker tests

Do not use arbitrary timing sleeps such as:

```python
await asyncio.sleep(1)
```

Prefer:

- `asyncio.Event`
- controlled fake dependencies
- explicit completion signals
- queue joins where appropriate

Tests must not depend on machine speed.

## Mocking

Mock only boundaries where using the real dependency would make tests:

- nondeterministic
- external
- expensive
- slow

Good candidates:

- LLM provider
- external HTTP APIs
- clock behavior when relevant

Usually do not mock:

- Pydantic validation
- SQLite
- your own small helper functions
- ticket state transitions

Prefer asserting outcomes over mock call counts.

## Test data

Use small, explicit data.

Prefer:

```python
ticket = {
    "id": "t-1",
    "subject": "Cannot log in",
    "body": "Password reset did not work",
}
```

Do not introduce factories until repetition becomes a real maintenance problem.

## Error paths

For important success paths, cover meaningful failures.

Examples:

- ticket not found
- duplicate ticket
- malformed model output
- LLM exception
- retry exhaustion
- invalid query parameters

Do not add artificial edge cases with little regression value.

## Running tests

Run focused tests first:

```bash
uv run pytest app/api/test_tickets.py
```

or:

```bash
uv run pytest app/api/test_tickets.py::test_create_ticket
```

Then run the full suite:

```bash
uv run pytest
```

Also run:

```bash
uv run ruff check .
uv run ruff format --check .
```

If formatting is required:

```bash
uv run ruff format .
```

Then rerun the checks.

## Review checklist

Before finishing, verify:

- the test is located next to the code it primarily covers
- shared fixtures are centralized only when actually shared
- the test would fail if the behavior regressed
- implementation details are not unnecessarily asserted
- temporary SQLite databases are used
- tests are independent
- no test depends on execution order
- no live LLM calls are made
- no arbitrary sleeps are used
- failure behavior is covered where important
- test names clearly describe expected behavior

## Scope control

Do not add extra testing libraries unless a current requirement justifies them.

Prefer the existing stack
