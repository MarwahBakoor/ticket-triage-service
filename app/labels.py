"""The labels a ticket can be classified with.

These are rules of the service itself, not of any one layer: the prompt
lists them, validation enforces them on model output, and the API exposes
them. Keeping them here means none of those layers imports another.
The database repeats them as CHECK constraints.
"""

from enum import StrEnum


class TicketCategory(StrEnum):
    BILLING = "billing"
    TECHNICAL = "technical"
    ACCOUNT = "account"
    OTHER = "other"


class TicketPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
