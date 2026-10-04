---
name: implement-task
description: Implement a small feature or bug fix in the ticket-triage FastAPI service using a test-first, minimal-change workflow. Use when adding or changing application behavior.
---

# Implement Task

Use this workflow when implementing a feature or fixing behavior in this repository.

## 1. Understand the existing code first

Before editing:

- inspect the relevant application files
- inspect the nearest existing tests
- inspect `AGENTS.md`
- identify existing conventions before creating new ones

Do not create a new architectural pattern if an existing one is sufficient.

## 2. Define the behavior

Translate the requested change into observable behavior.

Identify:

- input
- expected output
- database effects
- HTTP status behavior, if applicable
- failure cases
- concurrency or idempotency implications, if applicable

Keep scope limited to the requested behavior.

## 3. Write or update tests first

Add the smallest useful failing test that demonstrates the required behavior.

Prefer testing public behavior.

Examples:

- HTTP endpoint response
- persisted ticket state
- classification validation
- retry behavior

Avoid mocking internal functions merely to assert that they were called.

## 4. Implement the minimum code

Write the smallest implementation that makes the test pass.

Prefer:

- explicit control flow
- parameterized SQL
- existing helpers
- standard-library functionality

Avoid:

- speculative abstractions
- unrelated refactoring
- new dependencies
- generic frameworks for a single use case

## 5. Check important invariants

For ticket-related changes, verify relevant invariants:

- ticket IDs stay unique
- duplicate ingestion does not cause duplicate classification
- classification does not happen in the creation request
- model output is parsed and validated before persistence
- invalid classification values never reach successful stored state
- ticket content remains untrusted data
- database operations remain safe under concurrent requests where relevant

## 6. Run verification

Run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
