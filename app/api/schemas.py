from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.labels import TicketCategory, TicketPriority


class TicketOrder(StrEnum):
    OLDEST = "oldest"
    NEWEST = "newest"
    # High, medium, low, then unclassified; oldest first within each.
    PRIORITY = "priority"


class ClassificationJobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    CLASSIFIED = "classified"
    FAILED = "failed"


class TicketCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "t-1001",
                    "subject": "Charged twice this month",
                    "body": "I see two charges of 49.00 on my card. Can you refund one?",
                }
            ]
        }
    )

    id: str = Field(
        min_length=1,
        description="Unique id, chosen by you.",
    )
    # Required, but may be empty: emailed tickets can arrive without a subject.
    subject: str = Field(description="May be empty.")
    body: str = Field(min_length=1, description="The customer's message.")


class TicketResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "t-1001",
                    "subject": "Charged twice this month",
                    "body": "I see two charges of 49.00 on my card. Can you refund one?",
                    "category": "billing",
                    "priority": "medium",
                    "summary": "Customer was charged twice and wants a refund.",
                    "created_at": "2026-10-10T11:08:58.961142Z",
                    "updated_at": "2026-10-10T11:08:58.962843Z",
                    "classification_status": "classified",
                }
            ]
        }
    )

    id: str
    subject: str
    body: str
    category: TicketCategory | None = Field(description="Null until classified.")
    priority: TicketPriority | None = Field(description="Null until classified.")
    summary: str | None = Field(description="Null until classified.")
    created_at: datetime = Field(description="When it was submitted (UTC).")
    updated_at: datetime = Field(description="When it last changed (UTC).")
    classification_status: ClassificationJobStatus = Field(
        description="`failed` means no valid classification after 3 attempts."
    )


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunResponse(BaseModel):
    id: int
    ticket_id: str
    run_number: int = Field(
        description="1 for a ticket's first attempt, 2 for its retry, …"
    )
    status: RunStatus
    error: str | None = Field(
        description="Why a failed run failed, as fixed text; null otherwise."
    )
    started_at: datetime
    finished_at: datetime | None = Field(description="Null while the run is running.")


class RunSummary(BaseModel):
    running: int
    completed: int
    failed: int
    total: int
