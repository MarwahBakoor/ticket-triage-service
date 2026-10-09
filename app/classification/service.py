from app.db.tickets import (
    complete_classification,
    get_classification_job,
    get_ticket,
    mark_job_failed,
    mark_job_processing,
    record_failed_attempt,
)
from app.llm.client import LLMClient
from app.llm.prompts import build_classification_prompt
from app.llm.validation import ClassificationError, parse_classification

MAX_ATTEMPTS = 3


async def classify_ticket(ticket_id: str, llm: LLMClient) -> bool:
    """Classify a pending ticket, retrying failed attempts up to MAX_ATTEMPTS.

    Returns True only if the ticket was classified.
    """
    ticket = get_ticket(ticket_id)
    if ticket is None or not mark_job_processing(ticket_id):
        return False

    prompt = build_classification_prompt(ticket["subject"], ticket["body"])
    while True:
        # Checked before each call: a job recovered after a crash may already
        # have used every attempt.
        job = get_classification_job(ticket_id)
        if job is None:
            return False
        if job["attempts"] >= MAX_ATTEMPTS:
            mark_job_failed(ticket_id)
            return False

        # Errors are stored as fixed text so untrusted model output never leaks in.
        try:
            raw_output = await llm.classify(prompt)
        except Exception as error:  # noqa: BLE001 - any client error is retryable
            last_error = f"LLM call failed: {type(error).__name__}"
        else:
            try:
                result = parse_classification(raw_output)
            except ClassificationError:
                last_error = "Model output was not a valid classification"
            else:
                return complete_classification(ticket_id, result)

        if not record_failed_attempt(ticket_id, last_error):
            return False
