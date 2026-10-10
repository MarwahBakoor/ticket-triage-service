# Ticket Triage Service

Submit customer support tickets and get each one automatically sorted into a
**category** (billing, technical, account, other) and a **priority** (low,
medium, high), with a one-sentence **summary**. It comes with a web dashboard
and a JSON API.

## Quick start

You need **Python 3.12+** and **[uv](https://docs.astral.sh/uv/getting-started/installation/)**.

```sh
git clone https://github.com/MarwahBakoor/ticket-triage-service.git
cd ticket-triage-service
uv sync                                  # install dependencies
uv run uvicorn app.main:app --reload     # start the service
```

Open **<http://127.0.0.1:8000/>**. To see it with data, load the sample
tickets from a second terminal:

```sh
uv run python scripts/load_samples.py
```

The ten samples appear on the dashboard and are classified within moments.

## Running the service

Start it from the project folder:

```sh
uv run uvicorn app.main:app --reload
```

- `--reload` restarts the service when you change code. Leave it out for a
  normal run.
- Use another port with `--port 8001`.
- Stop it with `Ctrl+C`. Tickets are saved, and anything left unfinished is
  picked up again on the next start.

Tickets are stored in `tickets.db` in the folder you start the service from.
It is created automatically on first run.

| Link | What it is |
| --- | --- |
| <http://127.0.0.1:8000/> | The dashboard |
| <http://127.0.0.1:8000/docs> | Interactive API documentation |
| <http://127.0.0.1:8000/health> | Health check, returns `{"status": "ok"}` |

### Configuration

Set these environment variables before starting the service:

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_PATH` | `tickets.db` | Where to store tickets. |
| `CLASSIFICATION_WORKERS` | `4` | How many tickets are classified at the same time. Must be at least 1. |

```sh
DATABASE_PATH=/tmp/demo.db CLASSIFICATION_WORKERS=2 uv run uvicorn app.main:app
```

### Loading sample tickets

`scripts/load_samples.py` submits the ten tickets in
`sample_data/tickets.json` (`t-1001` to `t-1010`) to a running service:

```sh
uv run python scripts/load_samples.py                        # service on port 8000
uv run python scripts/load_samples.py http://127.0.0.1:8001  # another address
```

It is safe to run more than once: tickets that already exist are left
unchanged.

### About the classifier

No real AI model is connected yet. The service uses a built-in stand-in that
classifies by keywords, so results are plausible but not always right. On
purpose, every 4th classification attempt fails and is retried automatically,
so you can see retries happen. A ticket that fails 3 times is marked
**Failed**.

## Using the dashboard

The dashboard has two tabs at the top.

**Tickets** is where you work with tickets:

- **Submit a ticket** with **New ticket** (or press `N`). An id is suggested
  for you, the subject is optional, and **Try an example** fills in a sample.
- **Filter** by category and priority with the chips above the list.
- **Sort** by oldest, newest or priority with the **Sort** control.
- **Open a ticket** by clicking it. You'll see the full message, its
  classification and its progress, which updates by itself while the ticket is
  being classified.

**Metrics** shows how classification is going: totals, tickets still in the
queue, classified and failed counts, and breakdowns by category and priority.
Click any breakdown to see those tickets.

Everything updates live, so there is no need to refresh. Filters, sorting and
open tickets are part of the page address, so you can bookmark or share a view.

| Key | Action |
| --- | --- |
| `T` / `M` | Go to Tickets / Metrics |
| `N` | New ticket |
| `S` | Change sort order |
| `R` | Refresh now |
| `J` / `K` | Next / previous ticket while one is open |
| `Esc` | Close the open ticket or form |

## Using the API

Submit a ticket. It is accepted straight away and classified in the
background:

```sh
curl -X POST http://127.0.0.1:8000/tickets \
  -H 'Content-Type: application/json' \
  -d '{"id": "t-2001", "subject": "API returning 500s", "body": "Every export call fails since 09:00."}'
```

Check on it until `classification_status` is `completed` or `failed`:

```sh
curl http://127.0.0.1:8000/tickets/t-2001
```

List tickets, with optional filters, sort order and paging:

```sh
curl "http://127.0.0.1:8000/tickets?category=technical&order=priority&limit=10"
```

See **[API.md](API.md)** for every endpoint, parameter and error, or try the
API in your browser at <http://127.0.0.1:8000/docs>.

## Project structure

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
├── API.md                  API reference
├── DESIGN.md               How the service works inside
├── AGENTS.md               Conventions for contributors
└── pyproject.toml          Dependencies and tool settings
```

Tests sit next to the code they cover, as `test_*.py` files inside `app/`.

## Running tests and checks

```sh
uv run pytest                 # tests
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
```

Tests use their own temporary databases and never touch your `tickets.db`.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| `uv: command not found` | Install uv: <https://docs.astral.sh/uv/getting-started/installation/> |
| `address already in use` | Something else is using port 8000. Start with `--port 8001` and open that port instead. |
| Dashboard says **Can't reach the API** | The service isn't running, or is on another port. Start it and the dashboard reconnects by itself. |
| The loader script fails with `Connection refused` | Start the service first, or pass its address: `uv run python scripts/load_samples.py http://127.0.0.1:8001` |
| Tickets you loaded aren't there | The service may be using a different `tickets.db`. Start it from the project folder, or set `DATABASE_PATH`. |
| You want to start over with no tickets | Stop the service and delete `tickets.db`. **This deletes all tickets.** |

## Learn more

- [API.md](API.md): the full API reference.
- [DESIGN.md](DESIGN.md): how the service works inside and why.
- [AGENTS.md](AGENTS.md): project structure and conventions for contributors.
