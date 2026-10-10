import asyncio
import logging
import os

from app import constants
from app.classification.service import classify_claimed_ticket
from app.db.tickets import claim_next_job
from app.llm.client import LLMClient

logger = logging.getLogger(__name__)


def worker_count_from_env() -> int:
    """Read CLASSIFICATION_WORKERS, defaulting to DEFAULT_WORKER_COUNT."""
    raw = os.environ.get("CLASSIFICATION_WORKERS", str(constants.DEFAULT_WORKER_COUNT))
    try:
        count = int(raw)
    except ValueError:
        raise ValueError(
            f"CLASSIFICATION_WORKERS must be a positive integer, got {raw!r}"
        ) from None
    if count < 1:
        raise ValueError(
            f"CLASSIFICATION_WORKERS must be a positive integer, got {raw!r}"
        )
    return count


class ClassificationWorkers:
    """Poll the database for pending tickets with a fixed number of workers.

    Each worker claims the ticket that has waited longest, classifies it, and
    asks again. When nothing is pending it sleeps for POLL_INTERVAL_SECONDS.
    The database is the queue, so a saved ticket is always found. At most
    `worker_count` classifications run at once. Must be used from a single
    event loop.
    """

    def __init__(self, llm: LLMClient, worker_count: int) -> None:
        if worker_count < 1:
            raise ValueError("worker_count must be at least 1")
        self._llm = llm
        self._worker_count = worker_count
        self._tasks: list[asyncio.Task[None]] = []

    def start(self) -> None:
        if self._tasks:
            raise RuntimeError("classification workers already started")
        self._tasks = [
            asyncio.create_task(self._run(), name=f"classification-worker-{number}")
            for number in range(self._worker_count)
        ]

    async def stop(self) -> None:
        """Cancel workers; interrupted jobs stay in the database as processing."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def _run(self) -> None:
        while True:
            try:
                ticket_id = await asyncio.to_thread(claim_next_job)
            except Exception:
                # A locked or unavailable database must not end the worker.
                logger.exception("Could not claim a ticket")
                ticket_id = None
            if ticket_id is None:
                await asyncio.sleep(constants.POLL_INTERVAL_SECONDS)
                continue
            try:
                await classify_claimed_ticket(ticket_id, self._llm)
            except Exception:
                logger.exception("Classification of ticket %r crashed", ticket_id)
