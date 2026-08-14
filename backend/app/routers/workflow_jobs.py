from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.workflow.definition import service
from app.workflow.definition.loader import JobDefinitionParseError
from app.workflow.definition.schemas import (
    JobDefinition,
    JobDefinitionStoreRequest,
    JobDefinitionStoreResult,
    JobDefinitionValidateRequest,
    JobDefinitionValidateResponse,
    ValidationErrorOut,
)
from app.workflow.definition.service import DuplicateJobVersionError
from app.workflow.runtime import service as runtime_service
from app.workflow.runtime.instance import ParameterValidationError
from app.workflow.runtime.schemas import JobExecutionOut, LaunchJobRequest
from app.workflow.runtime.service import PreconditionError

router = APIRouter(prefix="/api/workflow/jobs", tags=["workflow"])


@router.post("/validate", response_model=JobDefinitionValidateResponse)
def validate_job(payload: JobDefinitionValidateRequest, db: Session = Depends(get_db)):
    try:
        definition, errors = service.validate_yaml(db, payload.yaml)
    except JobDefinitionParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return JobDefinitionValidateResponse(
        job_name=definition.job_name,
        version=definition.version,
        validation_status="invalid" if errors else "valid",
        validation_errors=[ValidationErrorOut(**e.to_dict()) for e in errors],
    )


@router.post("", response_model=JobDefinitionStoreResult, status_code=201)
def store_job(payload: JobDefinitionStoreRequest, db: Session = Depends(get_db)):
    try:
        row, errors = service.store_definition(db, payload.yaml, activate=payload.activate)
    except JobDefinitionParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DuplicateJobVersionError as exc:
        raise HTTPException(
            status_code=409, detail=[e.to_dict() for e in exc.errors]
        ) from exc

    db.commit()
    db.refresh(row)
    return JobDefinitionStoreResult(
        definition=JobDefinition.model_validate(row),
        validation_errors=[ValidationErrorOut(**e.to_dict()) for e in errors],
    )


@router.post("/{job_name}/activate/{version}", response_model=JobDefinition)
def activate_job(job_name: str, version: int, db: Session = Depends(get_db)):
    try:
        row = service.activate_definition(db, job_name, version)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    db.commit()
    db.refresh(row)
    return JobDefinition.model_validate(row)


@router.get("/{job_name}", response_model=JobDefinition)
def get_active_job(job_name: str, db: Session = Depends(get_db)):
    row = service.get_active_definition(db, job_name)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No active definition for job '{job_name}'")
    return JobDefinition.model_validate(row)


@router.post("/{job_name}/launch", response_model=JobExecutionOut, status_code=202)
def launch_job(job_name: str, payload: LaunchJobRequest, db: Session = Depends(get_db)):
    try:
        execution = runtime_service.launch_job(db, job_name, payload.parameters, triggered_by="api")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ParameterValidationError, PreconditionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    db.commit()
    db.refresh(execution)
    return runtime_service.to_execution_out(db, execution)
