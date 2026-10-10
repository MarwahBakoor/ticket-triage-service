import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request, status

from app.api.schemas import TicketCreate, TicketOrder, TicketResponse
from app.db.tickets import (
    create_ticket,
    get_ticket,
    list_tickets,
    reset_for_reclassification,
)
from app.labels import TicketCategory, TicketPriority

router = APIRouter(prefix="/tickets", tags=["tickets"])

NOT_FOUND_RESPONSE = {
    status.HTTP_404_NOT_FOUND: {
        "description": "No ticket has this id.",
        "content": {"application/json": {"example": {"detail": "Ticket not found"}}},
    }
}


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TicketResponse,
    summary="Submit a ticket",
    description=(
        "Classification happens in the background, so the ticket comes back "
        "`pending`. Resubmitting an existing id returns the stored ticket "
        "unchanged."
    ),
    response_description="The stored ticket.",
)
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


@router.get(
    "",
    response_model=list[TicketResponse],
    summary="List tickets",
    description="Filters only match classified tickets.",
    response_description="A page of tickets, possibly empty.",
)
def read_tickets(
    category: Annotated[
        TicketCategory | None, Query(description="Only tickets in this category.")
    ] = None,
    priority: Annotated[
        TicketPriority | None, Query(description="Only tickets with this priority.")
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=100, description="Maximum number of tickets to return.")
    ] = 20,
    offset: Annotated[int, Query(ge=0, description="Number of tickets to skip.")] = 0,
    order: Annotated[
        TicketOrder,
        Query(description="`priority` puts high first and unclassified last."),
    ] = TicketOrder.OLDEST,
) -> list[TicketResponse]:
    stored = list_tickets(category, priority, limit, offset, order)
    return [TicketResponse.model_validate(ticket) for ticket in stored]


@router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
    summary="Get a ticket",
    description="Poll until `classification_status` is `classified` or `failed`.",
    responses=NOT_FOUND_RESPONSE,
)
def read_ticket(
    ticket_id: Annotated[
        str, Path(description="The id the ticket was submitted with.")
    ],
) -> TicketResponse:
    stored = get_ticket(ticket_id)
    if stored is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    return TicketResponse.model_validate(stored)


@router.post(
    "/{ticket_id}/reclassify",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TicketResponse,
    summary="Reclassify a ticket",
    description=(
        "Only for `classified` or `failed` tickets. The old result is cleared "
        "and the ticket goes back to `pending`."
    ),
    response_description="The ticket, now pending.",
    responses=NOT_FOUND_RESPONSE
    | {
        status.HTTP_409_CONFLICT: {
            "description": "The ticket is still being classified.",
            "content": {
                "application/json": {
                    "example": {"detail": "Ticket is still being classified"}
                }
            },
        }
    },
)
async def reclassify_ticket(
    ticket_id: Annotated[
        str, Path(description="The id the ticket was submitted with.")
    ],
    request: Request,
) -> TicketResponse:
    if not await asyncio.to_thread(reset_for_reclassification, ticket_id):
        if await asyncio.to_thread(get_ticket, ticket_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Ticket is still being classified"
        )
    # Only the request that reset the job enqueues it, on the event loop thread.
    workers = getattr(request.app.state, "classification_workers", None)
    if workers is not None:
        workers.enqueue(ticket_id)
    stored = await asyncio.to_thread(get_ticket, ticket_id)
    if stored is None:
        raise RuntimeError(f"ticket {ticket_id!r} disappeared after reset")
    return TicketResponse.model_validate(stored)
