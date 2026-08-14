from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ErrorResponse, error
from app.workflow import registration
from app.workflow.schemas import StepDeclaration, StepRegistration, StepRegistrationResult

router = APIRouter(prefix="/api/workflow/steps", tags=["Workflow Steps"])


@router.post(
    "",
    response_model=StepRegistrationResult,
    summary="Register or update a lifecycle step",
    response_description="The stored registration, plus any contract-change warnings.",
    operation_id="register_step",
)
def register_step(payload: StepDeclaration, db: Session = Depends(get_db)):
    """
    Upserts by `step_name`. If this call declares a new major version of an
    artifact type the step produces, every other registered step whose
    `consumes` range can no longer accept it is reported in `warnings` — see
    10-ENGINE-CONCEPTS.md's contract-change detection. Registration succeeds
    regardless; warnings never block it.
    """
    row, created, warnings = registration.register_step(db, payload)
    db.commit()
    db.refresh(row)
    return StepRegistrationResult(
        step=StepRegistration.model_validate(row),
        created=created,
        warnings=warnings,
    )


@router.get(
    "",
    response_model=list[StepRegistration],
    summary="List registered lifecycle steps",
    response_description="Every registered step, ordered by lifecycle_step_no.",
    operation_id="list_steps",
)
def list_steps(db: Session = Depends(get_db)):
    return [StepRegistration.model_validate(row) for row in registration.list_steps(db)]


@router.get(
    "/{step_name}",
    response_model=StepRegistration,
    summary="Get a registered lifecycle step",
    response_description="The step's registration.",
    operation_id="get_step",
    responses={404: {"model": ErrorResponse, "description": "No step is registered with this step_name."}},
)
def get_step(step_name: str, db: Session = Depends(get_db)):
    row = registration.get_step(db, step_name)
    if row is None:
        raise error(404, f"Step '{step_name}' not found", code="NOT_FOUND")
    return StepRegistration.model_validate(row)
