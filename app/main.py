import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import tickets
from app.db.schema import initialize_database
from app.db.tickets import recover_unfinished_jobs
from app.llm.client import LLMClient
from app.llm.fake import KeywordFakeLLMClient
from app.workers.classification import ClassificationWorkers, worker_count_from_env

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


app = FastAPI(lifespan=lifespan)
# No real provider is wired in; a keyword fake keeps the service usable locally.
app.state.llm_client = KeywordFakeLLMClient(broken_every=4)
app.include_router(tickets.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
