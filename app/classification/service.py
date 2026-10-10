import asyncio

from app import constants
from app.db.tickets import (
    complete_classification,
    get_classification_job,
    get_ticket,
    mark_job_failed,
    record_failed_attempt,
    start_run,
)
from app.llm.client import LLMClient
from app.llm.prompts import build_classification_prompt
from app.llm.validation import ClassificationError, parse_classification


def retry_delay(failed_attempts: int) -> float:
    """Seconds to wait before the next attempt: 1, 2, 4, … times the base."""
    return constants.RETRY_BASE_DELAY_SECONDS * 2 ** (failed_attempts - 1)


async def classify_claimed_ticket(ticket_id: str, llm: LLMClient) -> bool:
    """Classify a ticket whose job the caller has claimed, with retries.

    Retries failed attempts up to MAX_ATTEMPTS. Returns True only if the
    ticket was classified. Database calls run in a thread so a locked
    database never blocks the event loop.
    """
    ticket = await asyncio.to_thread(get_ticket, ticket_id)
    if ticket is None:
        # Only a damaged database has a job without its ticket. Fail the job
        # rather than leave it processing.
        await asyncio.to_thread(mark_job_failed, ticket_id)
        return False

    prompt = build_classification_prompt(ticket["subject"], ticket["body"])
    while True:
        # Checked before each call: a job recovered after a crash may already
        # have used every attempt.
        job = await asyncio.to_thread(get_classification_job, ticket_id)
        if job is None:
            return False
        if job["attempts"] >= constants.MAX_ATTEMPTS:
            await asyncio.to_thread(mark_job_failed, ticket_id)
            return False
        if job["attempts"]:
            # Back off so a briefly overloaded or rate-limited provider is not
            # hit again at once. The worker stays busy while it waits.
            await asyncio.sleep(retry_delay(job["attempts"]))

        # Each attempt is recorded as its own run.
        run_id = await asyncio.to_thread(start_run, ticket_id)
        if run_id is None:
            return False

        # Errors are stored as fixed text so untrusted model output never leaks in.
        try:
            raw_output = await asyncio.wait_for(
                llm.classify(prompt), constants.LLM_TIMEOUT_SECONDS
            )
        except Exception as error:  # noqa: BLE001 - any client error is retryable
            run_error = f"LLM call failed: {type(error).__name__}"
        else:
            try:
                result = parse_classification(raw_output)
            except ClassificationError:
                run_error = "Model output was not a valid classification"
            else:
                return await asyncio.to_thread(
                    complete_classification, ticket_id, run_id, result
                )

        if not await asyncio.to_thread(
            record_failed_attempt, ticket_id, run_id, run_error
        ):
            return False
