from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TicketCategory(StrEnum):
    BILLING = "billing"
    TECHNICAL = "technical"
    ACCOUNT = "account"
    OTHER = "other"


class TicketPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ClassificationJobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TicketCreate(BaseModel):
    id: str = Field(min_length=1)
    # Required, but may be empty: emailed tickets can arrive without a subject.
    subject: str
    body: str = Field(min_length=1)


class TicketResponse(BaseModel):
    id: str
    subject: str
    body: str
    category: TicketCategory | None
    priority: TicketPriority | None
    summary: str | None
    created_at: datetime
    updated_at: datetime
    classification_status: ClassificationJobStatus
