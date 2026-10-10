from typing import Annotated

from fastapi import APIRouter, Query

from app.api.schemas import RunResponse, RunStatus, RunSummary
from app.db.runs import count_runs_by_status, list_runs

# Internal: feeds the dashboard's metrics view. Not part of the public API, so
# it is left out of the OpenAPI schema and docs/API.md and may change freely.
# The service has no authentication, so this hides the routes rather than
# protecting them.
router = APIRouter(prefix="/internal/runs", include_in_schema=False)


@router.get(
    "",
    response_model=list[RunResponse],
    summary="List classification runs",
    description=(
        "Every attempt to classify a ticket is a run. A ticket whose run "
        "fails is retried, up to 3 attempts, so it can have several runs. "
        "Returned newest first."
    ),
)
def read_runs(
    status: Annotated[
        RunStatus | None, Query(description="Only runs in this status.")
    ] = None,
    ticket_id: Annotated[
        str | None, Query(description="Only runs for this ticket.")
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=100, description="Maximum number of runs to return.")
    ] = 20,
    offset: Annotated[int, Query(ge=0, description="Number of runs to skip.")] = 0,
) -> list[RunResponse]:
    return [
        RunResponse.model_validate(run)
        for run in list_runs(status, ticket_id, limit, offset)
    ]


@router.get(
    "/summary",
    response_model=RunSummary,
    summary="Count runs by status",
)
def read_run_summary() -> RunSummary:
    counts = count_runs_by_status()
    return RunSummary(**counts, total=sum(counts.values()))
