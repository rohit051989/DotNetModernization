from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.workflow import registration
from app.workflow.schemas import StepDeclaration, StepRegistration, StepRegistrationResult

router = APIRouter(prefix="/api/workflow/steps", tags=["workflow"])


@router.post("", response_model=StepRegistrationResult)
def register_step(payload: StepDeclaration, db: Session = Depends(get_db)):
    row, created, warnings = registration.register_step(db, payload)
    db.commit()
    db.refresh(row)
    return StepRegistrationResult(
        step=StepRegistration.model_validate(row),
        created=created,
        warnings=warnings,
    )


@router.get("", response_model=list[StepRegistration])
def list_steps(db: Session = Depends(get_db)):
    return [StepRegistration.model_validate(row) for row in registration.list_steps(db)]


@router.get("/{step_name}", response_model=StepRegistration)
def get_step(step_name: str, db: Session = Depends(get_db)):
    row = registration.get_step(db, step_name)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Step '{step_name}' not found")
    return StepRegistration.model_validate(row)
