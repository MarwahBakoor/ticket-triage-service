import asyncio
import json
from collections import deque
from collections.abc import Iterable

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
