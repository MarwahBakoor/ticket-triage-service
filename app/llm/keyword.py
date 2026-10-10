"""The stand-in model the service runs on while no real provider is wired in.

It classifies by keyword matching and sometimes answers with broken output on
purpose, so the validation and retry paths run during local use. The test
doubles live in `app.llm.fake`; nothing here is test-only.
"""

import json
import re

from app.llm.prompts import TICKET_END, TICKET_START

# What a real model's output tends to look like when it goes wrong. Each one
# must be rejected by validation; the keyword client cycles through them.
_EXAMPLE = {
    "category": "billing",
    "priority": "high",
    "summary": "Customer was charged twice.",
}
BROKEN_RESPONSES = (
    '{"category": "billing", "priority": "high"',  # Malformed JSON.
    json.dumps(_EXAMPLE | {"category": "refunds"}),  # Unknown category.
    json.dumps(_EXAMPLE | {"priority": "urgent"}),  # Unknown priority.
    f"Sure! Here is the classification:\n{json.dumps(_EXAMPLE)}",  # Prose.
)


# First matching category wins, so specific technical failures beat incidental
# billing or account words in the same ticket.
_CATEGORY_PATTERNS = [
    ("technical", r"\b(error|e_timeout|500s?|api|export|upload\w*|broken|crash\w*)\b"),
    ("account", r"\b(log ?in|password|email address|account|sign ?in)\b"),
    ("billing", r"\b(charge[sd]?|overcharged|refund|invoices?|billing|subscription)\b"),
]
_LOW_PRIORITY_PATTERN = r"\b(not urgent|nice to have|feature request)\b"
_HIGH_PRIORITY_PATTERN = r"\b(urgent|blocking|production|outage)\b"


class KeywordLLMClient:
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
