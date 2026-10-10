import asyncio
import json
import re
from collections import deque
from collections.abc import Iterable

from app.llm.prompts import TICKET_END, TICKET_START

VALID_RESPONSE = json.dumps(
    {
        "category": "billing",
        "priority": "high",
        "summary": "Customer was charged twice.",
    }
)
MALFORMED_JSON_RESPONSE = '{"category": "billing", "priority": "high"'
INVALID_CATEGORY_RESPONSE = json.dumps(
    {
        "category": "refunds",
        "priority": "high",
        "summary": "Customer was charged twice.",
    }
)
INVALID_PRIORITY_RESPONSE = json.dumps(
    {
        "category": "billing",
        "priority": "urgent",
        "summary": "Customer was charged twice.",
    }
)
EMPTY_SUMMARY_RESPONSE = json.dumps(
    {"category": "billing", "priority": "high", "summary": ""}
)
PROSE_WRAPPED_RESPONSE = f"Sure! Here is the classification:\n{VALID_RESPONSE}"

# The ways a real model's output tends to go wrong, cycled by the keyword fake.
BROKEN_RESPONSES = (
    MALFORMED_JSON_RESPONSE,
    INVALID_CATEGORY_RESPONSE,
    INVALID_PRIORITY_RESPONSE,
    PROSE_WRAPPED_RESPONSE,
)


class FakeLLMClient:
    """Return scripted responses in order; exception instances are raised instead."""

    def __init__(self, responses: Iterable[str | Exception]) -> None:
        self._responses: deque[str | Exception] = deque(responses)
        self.prompts: list[str] = []

    async def classify(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            raise RuntimeError("FakeLLMClient has no scripted responses left")
        response = self._responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


class BlockingFakeLLMClient:
    """Hold every call until `release` is set, tracking how many run at once."""

    def __init__(self, response: str = VALID_RESPONSE) -> None:
        self.release = asyncio.Event()
        self.in_flight = 0
        self.max_in_flight = 0
        self.prompts: list[str] = []
        self._response = response
        self._changed = asyncio.Condition()

    async def classify(self, prompt: str) -> str:
        self.prompts.append(prompt)
        async with self._changed:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            self._changed.notify_all()
        try:
            await self.release.wait()
            return self._response
        finally:
            self.in_flight -= 1

    async def wait_for_in_flight(self, count: int) -> None:
        """Wait until at least `count` calls are blocked inside `classify`."""
        async with self._changed:
            await self._changed.wait_for(lambda: self.in_flight >= count)


# First matching category wins, so specific technical failures beat incidental
# billing or account words in the same ticket.
_CATEGORY_PATTERNS = [
    ("technical", r"\b(error|e_timeout|500s?|api|export|upload\w*|broken|crash\w*)\b"),
    ("account", r"\b(log ?in|password|email address|account|sign ?in)\b"),
    ("billing", r"\b(charge[sd]?|overcharged|refund|invoices?|billing|subscription)\b"),
]
_LOW_PRIORITY_PATTERN = r"\b(not urgent|nice to have|feature request)\b"
_HIGH_PRIORITY_PATTERN = r"\b(urgent|blocking|production|outage)\b"


class KeywordFakeLLMClient:
    """Classify by keyword matching so the service runs without a real model.

    Its answers are plausible, not accurate: like a real model, it can be
    steered by ticket text. Every `broken_every`-th call returns one of
    BROKEN_RESPONSES, in turn, so the retry path runs during local use; 0
    disables that.
    """

    def __init__(self, broken_every: int = 0) -> None:
        if broken_every < 0:
            raise ValueError("broken_every must not be negative")
        self._broken_every = broken_every
        self._calls = 0
        self._broken = 0

    async def classify(self, prompt: str) -> str:
        self._calls += 1
        if self._broken_every and self._calls % self._broken_every == 0:
            response = BROKEN_RESPONSES[self._broken % len(BROKEN_RESPONSES)]
            self._broken += 1
            return response

        ticket = json.loads(prompt.split(TICKET_START)[1].split(TICKET_END)[0])
        subject, body = ticket["subject"], ticket["body"]
        text = f"{subject}\n{body}".lower()
        category = next(
            (name for name, pattern in _CATEGORY_PATTERNS if re.search(pattern, text)),
            "other",
        )
        if re.search(_LOW_PRIORITY_PATTERN, text):
            priority = "low"
        elif re.search(_HIGH_PRIORITY_PATTERN, text):
            priority = "high"
        else:
            priority = "medium"
        topic = " ".join((subject.strip() or body.strip())[:80].split()).rstrip(".")
        summary = f"Customer wrote in about: {topic}."
        return json.dumps(
            {"category": category, "priority": priority, "summary": summary}
        )
