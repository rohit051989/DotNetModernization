import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ErrorResponse, error
from app.workflow.runtime import service
from app.workflow.runtime.schemas import JobExecutionDetail, JobExecutionOut, StepExecutionOut

router = APIRouter(prefix="/api/workflow/executions", tags=["Workflow Executions"])

_NOT_FOUND = {"model": ErrorResponse, "description": "No execution exists with this id."}


@router.post(
    "/{execution_id}/resume",
    response_model=JobExecutionOut,
    summary="Resume a FAILED or STOPPED execution",
    response_description="The new execution created to continue this instance.",
    operation_id="resume_execution",
    responses={
        404: _NOT_FOUND,
        409: {"model": ErrorResponse, "description": "The execution's batch_status is not FAILED or STOPPED — only those can be resumed."},
    },
)
def resume_execution(execution_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Creates a **new** execution of the same instance, using the same
    definition version the prior execution ran, and resumes from the first
    step that was not `COMPLETED` — honouring any step's
    `allow_start_if_complete` override. This is also how an
    `AWAITING_APPROVAL` gate is continued after external approval: the gate
    step is re-invoked, not skipped.
    """
    try:
        execution = service.resume_execution(db, execution_id)
    except LookupError as exc:
        raise error(404, str(exc), code="NOT_FOUND") from exc
    except ValueError as exc:
        raise error(409, str(exc), code="NOT_RESUMABLE") from exc

    db.commit()
    db.refresh(execution)
    return service.to_execution_out(db, execution)


@router.post(
    "/{execution_id}/stop",
    response_model=JobExecutionOut,
    summary="Stop a STARTING or STARTED execution",
    response_description="The now-STOPPED execution.",
    operation_id="stop_execution",
    responses={
        404: _NOT_FOUND,
        409: {"model": ErrorResponse, "description": "The execution's batch_status is not STARTING or STARTED — it has already reached a terminal state."},
    },
)
def stop_execution(execution_id: uuid.UUID, db: Session = Depends(get_db)):
    """Manual stop for an execution the operator wants to abandon — e.g. after
    a crash left one stuck. Sets `batch_status: STOPPED`; resume it later like
    any other stopped execution."""
    try:
        execution = service.stop_execution(db, execution_id)
    except LookupError as exc:
        raise error(404, str(exc), code="NOT_FOUND") from exc
    except ValueError as exc:
        raise error(409, str(exc), code="NOT_STOPPABLE") from exc

    db.commit()
    db.refresh(execution)
    return service.to_execution_out(db, execution)


@router.get(
    "/{execution_id}",
    response_model=JobExecutionDetail,
    summary="Get an execution, with its step history",
    response_description="The execution and every step execution recorded under it.",
    operation_id="get_execution",
    responses={404: _NOT_FOUND},
)
def get_execution(execution_id: uuid.UUID, db: Session = Depends(get_db)):
    execution = service.get_execution(db, execution_id)
    if execution is None:
        raise error(404, f"execution '{execution_id}' not found", code="NOT_FOUND")

    out = service.to_execution_out(db, execution)
    steps = service.to_step_execution_outs(db, execution)
    return JobExecutionDetail(**out.model_dump(), steps=steps)


@router.get(
    "",
    response_model=list[JobExecutionOut],
    summary="List workflow executions",
    response_description="Executions matching the filters, newest first.",
    operation_id="list_executions",
)
def list_executions(
    job_name: str | None = Query(None, description="Filter to one job definition, e.g. 'phase0-repository-discovery'."),
    batch_status: str | None = Query(None, description="Filter by batch status, e.g. 'COMPLETED' or 'FAILED'."),
    engagement_id: str | None = Query(
        None,
        description="Filter to executions whose job instance declares this engagement_id parameter. Only matches jobs that declare one.",
    ),
    repository_id: str | None = Query(
        None,
        description="Filter to executions whose job instance declares this repository_id parameter. Only matches jobs that declare one.",
    ),
    limit: int = Query(50, ge=1, le=500, description="Maximum executions to return."),
    offset: int = Query(0, ge=0, description="Number of executions to skip, for paging."),
    db: Session = Depends(get_db),
):
    """
    The canonical, flat execution collection — not nested under engagements
    or repositories, since the engagement is a job *parameter*, not an
    owner: a future wave-scoped job may have no `repository_id` at all. See
    `GET /api/engagements/{eid}/executions` for a pre-filtered convenience
    view over this same data.
    """
    executions = service.list_executions(
        db,
        job_name=job_name,
        batch_status=batch_status,
        engagement_id=engagement_id,
        repository_id=repository_id,
        limit=limit,
        offset=offset,
    )
    return [service.to_execution_out(db, e) for e in executions]


@router.get(
    "/{execution_id}/steps",
    response_model=list[StepExecutionOut],
    summary="List step executions for an execution",
    response_description="Step executions in start order.",
    operation_id="list_execution_steps",
    responses={404: _NOT_FOUND},
)
def get_execution_steps(execution_id: uuid.UUID, db: Session = Depends(get_db)):
    execution = service.get_execution(db, execution_id)
    if execution is None:
        raise error(404, f"execution '{execution_id}' not found", code="NOT_FOUND")
    return service.to_step_execution_outs(db, execution)
