import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.api.schemas import (
    TicketCategory,
    TicketCreate,
    TicketPriority,
    TicketResponse,
)
from app.db.tickets import create_ticket, get_ticket, list_tickets

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=TicketResponse)
async def submit_ticket(ticket: TicketCreate, request: Request) -> TicketResponse:
    """Accept a ticket for classification; duplicate ids return the stored ticket.

    Classification runs later on a worker. Only newly created tickets are
    enqueued, and only after their transaction has committed.
    """
    stored, created = await asyncio.to_thread(
        create_ticket, ticket.id, ticket.subject, ticket.body
    )
    # Enqueue on the event loop thread: asyncio.Queue is not thread-safe.
    workers = getattr(request.app.state, "classification_workers", None)
    if created and workers is not None:
        workers.enqueue(ticket.id)
    return TicketResponse.model_validate(stored)


@router.get("", response_model=list[TicketResponse])
def read_tickets(
    category: TicketCategory | None = None,
    priority: TicketPriority | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TicketResponse]:
    stored = list_tickets(category, priority, limit, offset)
    return [TicketResponse.model_validate(ticket) for ticket in stored]


@router.get("/{ticket_id}", response_model=TicketResponse)
def read_ticket(ticket_id: str) -> TicketResponse:
    stored = get_ticket(ticket_id)
    if stored is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    return TicketResponse.model_validate(stored)
