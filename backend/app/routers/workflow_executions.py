import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.workflow.runtime import service
from app.workflow.runtime.schemas import JobExecutionDetail, JobExecutionOut, StepExecutionOut

router = APIRouter(prefix="/api/workflow/executions", tags=["workflow"])


@router.post("/{execution_id}/resume", response_model=JobExecutionOut)
def resume_execution(execution_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        execution = service.resume_execution(db, execution_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    db.refresh(execution)
    return service.to_execution_out(db, execution)


@router.post("/{execution_id}/stop", response_model=JobExecutionOut)
def stop_execution(execution_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        execution = service.stop_execution(db, execution_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    db.refresh(execution)
    return service.to_execution_out(db, execution)


@router.get("/{execution_id}", response_model=JobExecutionDetail)
def get_execution(execution_id: uuid.UUID, db: Session = Depends(get_db)):
    execution = service.get_execution(db, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail=f"execution '{execution_id}' not found")

    out = service.to_execution_out(db, execution)
    steps = [
        StepExecutionOut.model_validate(se) for se in service.get_step_executions(db, execution_id)
    ]
    return JobExecutionDetail(**out.model_dump(), steps=steps)


@router.get("", response_model=list[JobExecutionOut])
def list_executions(
    job_name: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
):
    executions = service.list_executions(db, job_name=job_name, status=status)
    return [service.to_execution_out(db, e) for e in executions]


@router.get("/{execution_id}/steps", response_model=list[StepExecutionOut])
def get_execution_steps(execution_id: uuid.UUID, db: Session = Depends(get_db)):
    execution = service.get_execution(db, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail=f"execution '{execution_id}' not found")
    return [
        StepExecutionOut.model_validate(se) for se in service.get_step_executions(db, execution_id)
    ]
