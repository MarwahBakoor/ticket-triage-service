import asyncio
import logging
import os

from app import constants
from app.classification.service import classify_ticket
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
    """Classify queued ticket ids with a fixed number of worker tasks.

    Each worker handles one ticket at a time, so at most `worker_count`
    classifications run concurrently. Must be used from a single event loop.
    """

    def __init__(self, llm: LLMClient, worker_count: int) -> None:
        if worker_count < 1:
            raise ValueError("worker_count must be at least 1")
        self._llm = llm
        self._worker_count = worker_count
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []

    def enqueue(self, ticket_id: str) -> None:
        self._queue.put_nowait(ticket_id)

    def queued_count(self) -> int:
        """Return the number of ticket ids waiting for a worker."""
        return self._queue.qsize()

    def start(self) -> None:
        if self._tasks:
            raise RuntimeError("classification workers already started")
        self._tasks = [
            asyncio.create_task(self._run(), name=f"classification-worker-{number}")
            for number in range(self._worker_count)
        ]

    async def join(self) -> None:
        """Wait until every enqueued ticket id has been processed."""
        await self._queue.join()

    async def stop(self) -> None:
        """Cancel workers; interrupted jobs stay in the database as processing."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def _run(self) -> None:
        while True:
            ticket_id = await self._queue.get()
            try:
                await classify_ticket(ticket_id, self._llm)
            except Exception:
                logger.exception("Classification of ticket %r crashed", ticket_id)
            finally:
                self._queue.task_done()
