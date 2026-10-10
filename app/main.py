import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import runs, tickets
from app.db.schema import initialize_database
from app.db.tickets import recover_unfinished_jobs
from app.llm.client import LLMClient
from app.llm.fake import KeywordFakeLLMClient
from app.workers.classification import ClassificationWorkers, worker_count_from_env

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    llm: LLMClient | None = getattr(app.state, "llm_client", None)
    if llm is None:
        logger.warning("No LLM client configured; new tickets will stay pending")
        app.state.classification_workers = None
        yield
        return

    workers = ClassificationWorkers(llm, worker_count_from_env())
    app.state.classification_workers = workers
    # SQLite is the durable record; the queue is rebuilt from it on startup.
    for ticket_id in await asyncio.to_thread(recover_unfinished_jobs):
        workers.enqueue(ticket_id)
    workers.start()
    try:
        yield
    finally:
        await workers.stop()
        # Stopped workers must not receive tickets from a later request.
        app.state.classification_workers = None


app = FastAPI(
    title="Ticket Triage Service",
    version="0.1.0",
    summary="Ingest support tickets and classify them asynchronously with an LLM.",
    description=(
        "Submitting a ticket stores it and returns `202 Accepted` straight away; "
        "classification runs afterwards on a background worker. Poll the ticket "
        "and watch `classification_status` move from `pending` through "
        "`processing` to `completed` or `failed`. See `docs/API.md` for the "
        "full guide."
    ),
    openapi_tags=[
        {"name": "tickets", "description": "Submit, read and list tickets."},
        {"name": "service", "description": "Operational endpoints."},
    ],
    lifespan=lifespan,
)
# No real provider is wired in; a keyword fake keeps the service usable locally.
app.state.llm_client = KeywordFakeLLMClient(broken_every=4)
app.include_router(tickets.router)
app.include_router(runs.router)
# Served from the same origin as the API, so the dashboard needs no CORS setup.
app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/app/")


@app.get("/health", tags=["service"], summary="Liveness check")
def health() -> dict[str, str]:
    """Return `{"status": "ok"}` while the process is serving requests."""
    return {"status": "ok"}
