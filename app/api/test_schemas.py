import pytest
from pydantic import ValidationError

from app.api.schemas import (
    ClassificationJobStatus,
    TicketCategory,
    TicketCreate,
    TicketPriority,
    TicketResponse,
)


def ticket_response_data(**overrides) -> dict:
    return {
        "id": "t-1",
        "subject": "Cannot log in",
        "body": "Password reset did not work",
        "category": None,
        "priority": None,
        "summary": None,
        "created_at": "2026-10-09T12:00:00Z",
        "updated_at": "2026-10-09T12:00:00Z",
        "classification_status": "pending",
    } | overrides


def test_enum_values_match_allowed_values():
    assert {c.value for c in TicketCategory} == {
        "billing",
        "technical",
        "account",
        "other",
    }
    assert {p.value for p in TicketPriority} == {"low", "medium", "high"}
    assert {s.value for s in ClassificationJobStatus} == {
        "pending",
        "processing",
        "completed",
        "failed",
    }


def test_ticket_create_accepts_valid_payload():
    ticket = TicketCreate.model_validate(
        {"id": "t-1", "subject": "Cannot log in", "body": "Password reset failed"}
    )

    assert ticket.model_dump() == {
        "id": "t-1",
        "subject": "Cannot log in",
        "body": "Password reset failed",
    }


@pytest.mark.parametrize("missing", ["id", "subject", "body"])
def test_ticket_create_rejects_missing_field(missing):
    payload = {"id": "t-1", "subject": "Cannot log in", "body": "Reset failed"}
    del payload[missing]

    with pytest.raises(ValidationError):
        TicketCreate.model_validate(payload)


@pytest.mark.parametrize("empty", ["id", "subject", "body"])
def test_ticket_create_rejects_empty_field(empty):
    payload = {"id": "t-1", "subject": "Cannot log in", "body": "Reset failed"}
    payload[empty] = ""

    with pytest.raises(ValidationError):
        TicketCreate.model_validate(payload)


def test_ticket_response_allows_unclassified_ticket():
    ticket = TicketResponse.model_validate(ticket_response_data())

    data = ticket.model_dump(mode="json")
    assert data["category"] is None
    assert data["priority"] is None
    assert data["summary"] is None
    assert data["classification_status"] == "pending"


def test_ticket_response_serializes_classified_ticket():
    ticket = TicketResponse.model_validate(
        ticket_response_data(
            category="account",
            priority="high",
            summary="User cannot reset password.",
            classification_status="completed",
        )
    )

    data = ticket.model_dump(mode="json")
    assert data["category"] == "account"
    assert data["priority"] == "high"
    assert data["summary"] == "User cannot reset password."
    assert data["classification_status"] == "completed"
    assert data["created_at"] == "2026-10-09T12:00:00Z"


@pytest.mark.parametrize(
    "field",
    [
        {"category": "sales"},
        {"priority": "urgent"},
        {"classification_status": "unknown"},
    ],
)
def test_ticket_response_rejects_invalid_enum_values(field):
    with pytest.raises(ValidationError):
        TicketResponse.model_validate(ticket_response_data(**field))
