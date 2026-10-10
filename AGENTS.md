# Project structure

Follow this structure. Do not invent alternative layouts or move files without
a clear reason.

```text
app/
├── main.py
├── test_main.py
├── api/
│   ├── tickets.py
│   └── test_tickets.py
├── db/
│   ├── connection.py
│   ├── test_connection.py
│   ├── schema.py
│   ├── test_schema.py
│   ├── tickets.py
│   └── test_tickets.py
├── llm/
│   ├── client.py
│   ├── fake.py
│   ├── prompts.py
│   ├── validation.py
│   └── corresponding test files
├── classification/
│   ├── service.py
│   └── test_service.py
└── workers/
    ├── classification.py
    └── test_classification.py

docs/
├── API.md
└── DESIGN.md

frontend/
├── index.html
├── styles.css
└── app.js

sample_data/
└── tickets.json

scripts/
└── load_samples.py

.agents/
└── skills/
    ├── commit/SKILL.md
    ├── implement-task/SKILL.md
    └── testing/SKILL.md
```

Adapt the structure only when a concrete requirement justifies a change. Do not
create empty modules or directories merely to match this tree.

# Architecture boundaries

- `app/api/`: FastAPI routes, HTTP status codes, request and response handling.
- `app/db/`: SQLite connections, schema initialization, and explicit
  parameterized SQL.
- `app/llm/`: LLM interface, fake implementation, prompt construction, and
  raw-output validation.
- `app/classification/`: classification workflow, retries, and coordination
  between the LLM and database.
- `app/workers/`: asynchronous queue, worker lifecycle, concurrency, and startup
  recovery.
- `app/main.py`: application creation and lifecycle wiring, including serving
  the dashboard.
- `frontend/`: the static dashboard (plain HTML, CSS and JavaScript, no build
  step). It talks to the API only over HTTP and inserts ticket text as text,
  never as HTML.

# Database design

Use SQLite and Python's built-in `sqlite3` module. Do not introduce an ORM or
migration framework.

Keep this codebase free of foreign keys. Do not add foreign-key constraints,
SQL `REFERENCES` clauses, or enable SQLite foreign-key enforcement.
Handle any required relationship validation explicitly in application code.

# Testing conventions

- Co-locate tests next to the code they cover.
- Name test files `test_*.py`.
- Keep genuinely shared fixtures in `tests/conftest.py` only when needed.
- Use isolated temporary SQLite databases.
- Never use the development database in tests.
- Use deterministic fake LLM responses; never call a live LLM in automated
  tests.
- Follow `.agents/skills/testing/SKILL.md` when applicable.

# Before finishing a task

1. Review the diff for unnecessary files and structural deviations.
2. Run relevant tests, then the full test suite when practical.
3. Run `uv run ruff check .`.
4. Run `uv run ruff format --check .`.
5. Report any deviations from the agreed architecture and explain why they were
   necessary.
