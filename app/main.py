import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import constants
from app.api import runs, tickets
from app.db.schema import initialize_database
from app.db.tickets import recover_interrupted_jobs
from app.llm.client import LLMClient
from app.llm.keyword import KeywordLLMClient
from app.workers.classification import ClassificationWorkers, worker_count_from_env

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    llm: LLMClient | None = getattr(app.state, "llm_client", None)
    if llm is None:
        logger.warning("No LLM client configured; new tickets will stay pending")
        yield
        return

    # Workers poll the database for pending tickets. Jobs a stopped process
    # left processing go back to pending first, so workers claim them again.
    await asyncio.to_thread(recover_interrupted_jobs)
    workers = ClassificationWorkers(llm, worker_count_from_env())
    workers.start()
    try:
        yield
    finally:
        await workers.stop()


app = FastAPI(
    title="Ticket Triage Service",
    version="0.1.0",
    summary="Ingest support tickets and classify them asynchronously with an LLM.",
    description=(
        "Submit a ticket, then poll it until `classification_status` is "
        "`classified` or `failed`."
    ),
    openapi_tags=[
        {"name": "tickets", "description": "Submit, read and list tickets."},
        {"name": "service", "description": "Operational endpoints."},
    ],
    lifespan=lifespan,
)
# No real provider is wired in; a keyword stand-in keeps the service usable.
app.state.llm_client = KeywordLLMClient(broken_every=constants.FAKE_LLM_BROKEN_EVERY)
# Routers
app.include_router(tickets.router)
app.include_router(runs.router)
app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/app/")


@app.get("/health", tags=["service"], summary="Liveness check")
def health() -> dict[str, str]:
    """Return `{"status": "ok"}` while the process is serving requests."""
    return {"status": "ok"}
