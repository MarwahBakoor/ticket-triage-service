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
        "Store a ticket and queue it for classification. The response is "
        "returned before classification runs, so it has "
        "`classification_status: pending` and null classification fields.\n\n"
        "Submitting is idempotent by `id`: if the id already exists, the stored "
        "ticket is returned unchanged (also with `202`), the new subject and "
        "body are ignored, and it is not classified again."
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
    description=(
        "Return a page of tickets. `category` and `priority` filters match "
        "classified tickets only, because a ticket has neither until it is "
        "classified. Pagination is offset-based: request the next page with "
        "`offset + limit` until fewer than `limit` tickets come back."
    ),
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
        Query(
            description=(
                "`oldest` and `newest` sort by submission time. `priority` sorts "
                "high, medium, low, then unclassified, oldest first within each."
            )
        ),
    ] = TicketOrder.OLDEST,
) -> list[TicketResponse]:
    stored = list_tickets(category, priority, limit, offset, order)
    return [TicketResponse.model_validate(ticket) for ticket in stored]


@router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
    summary="Get a ticket",
    description=(
        "Return one ticket with its current classification status. Poll this "
        "after submitting to see the classification arrive."
    ),
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
    summary="Classify a ticket again",
    description=(
        "Queue a `classified` or `failed` ticket for a fresh classification, "
        "for example after a prompt change or a model outage. Its previous "
        "result is cleared, it gets a new set of attempts, and it is "
        "returned as `pending`.\n\n"
        "A ticket that is still `pending` or `processing` returns `409`, so "
        "repeating the request never queues a ticket twice."
    ),
    response_description="The ticket, now pending.",
    responses=NOT_FOUND_RESPONSE
    | {
        status.HTTP_409_CONFLICT: {
            "description": "The ticket is still pending or processing.",
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
