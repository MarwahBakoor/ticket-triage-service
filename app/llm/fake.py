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
