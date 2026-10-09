from fastapi import APIRouter, HTTPException, status

from app.api.schemas import TicketCreate, TicketResponse
from app.db.tickets import create_ticket, get_ticket

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=TicketResponse)
def submit_ticket(ticket: TicketCreate) -> TicketResponse:
    """Accept a ticket for classification; duplicate ids return the stored ticket."""
    stored, _ = create_ticket(ticket.id, ticket.subject, ticket.body)
    return TicketResponse.model_validate(stored)


@router.get("/{ticket_id}", response_model=TicketResponse)
def read_ticket(ticket_id: str) -> TicketResponse:
    stored = get_ticket(ticket_id)
    if stored is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    return TicketResponse.model_validate(stored)
