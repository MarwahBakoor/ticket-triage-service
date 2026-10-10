# Ticket Triage Service

Submit customer support tickets and each one is automatically given:

- a **category**: billing, technical, account or other
- a **priority**: low, medium or high
- a one-sentence **summary**

You can use it through a **web dashboard** or a **JSON API**.

## Contents

1. [Getting started](#getting-started)
2. [Using the dashboard](#using-the-dashboard)
3. [Using the API](#using-the-api)
4. [Configuration](#configuration)
5. [Good to know](#good-to-know)
6. [Development](#development)
7. [Troubleshooting](#troubleshooting)
8. [More documentation](#more-documentation)

## Getting started

### 1. Install the requirements

- **Python 3.12** or newer
- **uv**, the Python package manager:
  [installation guide](https://docs.astral.sh/uv/getting-started/installation/)

### 2. Download the project and its dependencies

```sh
git clone https://github.com/MarwahBakoor/ticket-triage-service.git
cd ticket-triage-service
uv sync
```

### 3. Start the service

```sh
uv run uvicorn app.main:app --reload
```

Leave this terminal open; the service runs until you press `Ctrl+C`.
(`--reload` restarts it automatically when you edit code.)

### 4. Open it

| Address | What it is |
| --- | --- |
| <http://127.0.0.1:8000/> | The dashboard |
| <http://127.0.0.1:8000/docs> | Interactive API documentation |
| <http://127.0.0.1:8000/health> | Health check, returns `{"status": "ok"}` |

### 5. Add sample tickets (optional)

The dashboard starts empty. To fill it with ten example tickets, run this in a
**second terminal** while the service is running:

```sh
uv run python scripts/load_samples.py
```

They appear on the dashboard within a few seconds and are classified shortly
after.
Running it again is safe; existing tickets are left unchanged.

## Using the dashboard

The dashboard has two tabs at the top: **Tickets** and **Metrics**.

### Tickets

| To | Do this |
| --- | --- |
| Submit a ticket | Click **New ticket** (or press `N`). An id is suggested, the subject is optional, and **Try an example** fills in a sample. |
| Filter | Click the category and priority chips above the list. |
| Sort | Choose **Oldest**, **Newest** or **Priority** in the **Sort** control. |
| See a ticket | Click it to open the full message, its classification and its progress. |

### Metrics

Shows how classification is going: the total number of tickets, how many are
waiting, classified or failed, and breakdowns by category and priority. Click
any breakdown to see those tickets.

### Tips

- Everything updates live, so there's no need to refresh.
- Filters, sorting and the open ticket are part of the page address, so you
  can bookmark or share a view.
- Keyboard shortcuts:

  | Key | Action |
  | --- | --- |
  | `T` / `M` | Go to Tickets / Metrics |
  | `N` | New ticket |
  | `S` | Change sort order |
  | `R` | Refresh now |
  | `J` / `K` | Next / previous ticket while one is open |
  | `Esc` | Close the open ticket or form |

## Using the API

**Submit a ticket.** It's accepted straight away and classified in the
background:

```sh
curl -X POST http://127.0.0.1:8000/tickets \
  -H 'Content-Type: application/json' \
  -d '{"id": "t-2001", "subject": "API returning 500s", "body": "Every export call fails since 09:00."}'
```

**Check on it** until `classification_status` is `completed` or `failed`:

```sh
curl http://127.0.0.1:8000/tickets/t-2001
```

**List tickets**, with optional filters, sort order and paging:

```sh
curl "http://127.0.0.1:8000/tickets?category=technical&order=priority&limit=10"
```

For every endpoint, parameter and error, see **[docs/API.md](docs/API.md)**,
or try the API in your browser at <http://127.0.0.1:8000/docs>.

## Configuration

Settings are environment variables, set when you start the service:

| Variable | Default | What it does |
| --- | --- | --- |
| `DATABASE_PATH` | `tickets.db` | The file tickets are saved in. |
| `CLASSIFICATION_WORKERS` | `4` | How many tickets are classified at the same time (at least 1). |

Example:

```sh
DATABASE_PATH=/tmp/demo.db CLASSIFICATION_WORKERS=2 uv run uvicorn app.main:app
```

To run on another port, add `--port`, e.g. `--port 8001`. Then point the
sample loader at it too:
`uv run python scripts/load_samples.py http://127.0.0.1:8001`.

## Good to know

- **Classification uses a stand-in, not a real AI model.** It classifies by
  keywords, so results are plausible but not always right.
- **Some attempts fail on purpose.** Every 4th classification attempt fails
  and is retried automatically, so you can see retries happen. A ticket that
  fails 3 times is marked **Failed**.
- **Your tickets are kept.** They're saved in `tickets.db` in the folder you
  start the service from, so they survive restarts. Tickets that were still
  being classified when you stopped the service are finished on the next
  start.
- **There's no login.** Run it on your own machine; don't expose it to the
  internet as it is.

## Development

### Project structure

```text
ticket-triage-service/
├── app/                    The service (Python, FastAPI)
│   ├── main.py             Starts the app and serves the dashboard
│   ├── api/                HTTP endpoints and request/response shapes
│   ├── db/                 SQLite storage
│   ├── llm/                Classifier interface, prompt and output checks
│   ├── classification/     Classifies one ticket, with retries
│   └── workers/            Background workers that process the queue
├── frontend/               The dashboard (HTML, CSS and JavaScript, no build step)
├── sample_data/
│   └── tickets.json        Ten example tickets
├── scripts/
│   └── load_samples.py     Loads the example tickets into a running service
├── tests/
│   └── conftest.py         Test setup shared by all tests
├── docs/
│   ├── API.md              API reference
│   └── DESIGN.md           How the service works inside
├── AGENTS.md               Conventions for contributors
└── pyproject.toml          Dependencies and tool settings
```

Tests sit next to the code they cover, as `test_*.py` files inside `app/`.

### Tests and checks

```sh
uv run pytest                 # run the tests
uv run ruff check .           # lint
uv run ruff format --check .  # check formatting
```

Tests use their own temporary databases and never touch your `tickets.db`.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `uv: command not found` | Install uv: [installation guide](https://docs.astral.sh/uv/getting-started/installation/). |
| `address already in use` | Another program is using port 8000. Start with `--port 8001` and use that port in the addresses above. |
| The dashboard says **Can't reach the API** | The service isn't running, or is on another port. Start it; the dashboard reconnects by itself. |
| The sample loader fails with `Connection refused` | Start the service first. If it's on another port, pass the address (see [Configuration](#configuration)). |
| Your tickets are missing | The service is probably using a different `tickets.db`. Start it from the project folder, or set `DATABASE_PATH`. |
| You want to start over | Stop the service and delete `tickets.db`. **This deletes all tickets.** |

## More documentation

- [docs/API.md](docs/API.md): full API reference.
- [docs/DESIGN.md](docs/DESIGN.md): how the service works inside, and why.
- [AGENTS.md](AGENTS.md): conventions for contributors.
