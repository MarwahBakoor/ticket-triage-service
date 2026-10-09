from fastapi import APIRouter, status

from app.api.schemas import TicketCreate, TicketResponse
from app.db.tickets import create_ticket

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=TicketResponse)
def submit_ticket(ticket: TicketCreate) -> TicketResponse:
    """Accept a ticket for classification; duplicate ids return the stored ticket."""
    stored, _ = create_ticket(ticket.id, ticket.subject, ticket.body)
    return TicketResponse.model_validate(stored)
