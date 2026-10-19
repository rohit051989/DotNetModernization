"""Step time limits (rbc-release-5): the defaults, the overrides, and what is in effect — changeable without code.

The defaults come from the settings (STEP_TIMEOUT_SECONDS, STEP_STALL_SECONDS); an override names a step, a
repository, or both (app.workflow.time_limits, which the command line uses too).
"""
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.db import get_db
from app.errors import ErrorResponse, error
from app.workflow import time_limits

router = APIRouter(prefix="/api/workflow/time-limits", tags=["Workflow Steps"])


class TimeLimitOverride(BaseModel):
    step_name: str | None = None
    repository_id: uuid.UUID | None = None
    timeout_seconds: int | None = Field(default=None, gt=0)
    stall_seconds: int | None = Field(default=None, gt=0)
    note: str | None = None


class TimeLimits(BaseModel):
    default_timeout_seconds: int
    default_stall_seconds: int
    project_seconds: int
    file_seconds: int
    overrides: list[TimeLimitOverride]


class EffectiveTimeLimit(BaseModel):
    step_name: str
    repository_id: uuid.UUID | None
    timeout_seconds: int
    timeout_from: str
    stall_seconds: int
    stall_from: str
    project_seconds: int
    file_seconds: int


def _out(row: models.StepTimeLimit) -> TimeLimitOverride:
    return TimeLimitOverride(step_name=row.step_name, repository_id=row.repository_id, timeout_seconds=row.timeout_seconds,
                             stall_seconds=row.stall_seconds, note=row.note)


def _list(db: Session) -> TimeLimits:
    return TimeLimits(default_timeout_seconds=settings.step_timeout_seconds, default_stall_seconds=settings.step_stall_seconds,
                      project_seconds=settings.step_project_seconds, file_seconds=settings.step_file_seconds,
                      overrides=[_out(r) for r in time_limits.overrides(db)])


def _repository(db: Session, repository_id: uuid.UUID | None) -> None:
    if repository_id is not None:
        repo = db.get(models.Repository, repository_id)
        if repo is None or repo.deleted_at is not None:
            raise error(404, f"no repository {repository_id}", code="NOT_FOUND")


@router.get("", response_model=TimeLimits, summary="The default time limits and every override",
            operation_id="list_time_limits")
def list_time_limits(db: Session = Depends(get_db)):
    return _list(db)


@router.get("/effective", response_model=EffectiveTimeLimit, summary="The limits in effect for a step, on a repository",
            operation_id="effective_time_limit", responses={404: {"model": ErrorResponse}})
def effective_time_limit(step_name: str = Query(...), repository_id: uuid.UUID | None = Query(None),
                         db: Session = Depends(get_db)):
    """The most specific wins: this step on this repository, then this repository, then this step, then the defaults."""
    _repository(db, repository_id)
    return EffectiveTimeLimit(step_name=step_name, repository_id=repository_id,
                              **time_limits.effective(db, step_name, repository_id))


@router.put("", response_model=TimeLimits, summary="Set an override for a step, a repository, or both",
            operation_id="set_time_limit", responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
def set_time_limit(payload: TimeLimitOverride, db: Session = Depends(get_db)):
    # TODO: gate to admins once auth exists — the limits apply to every engagement.
    _repository(db, payload.repository_id)
    try:
        time_limits.set_limit(db, payload.step_name, payload.repository_id, payload.timeout_seconds,
                              payload.stall_seconds, payload.note)
    except ValueError as exc:
        raise error(422, str(exc), code="INVALID_TIME_LIMIT") from exc
    db.commit()
    return _list(db)


@router.delete("", response_model=TimeLimits, summary="Clear an override, so the next level down applies",
               operation_id="clear_time_limit", responses={404: {"model": ErrorResponse}})
def clear_time_limit(step_name: str | None = Query(None), repository_id: uuid.UUID | None = Query(None),
                     db: Session = Depends(get_db)):
    # TODO: gate to admins once auth exists — the limits apply to every engagement.
    if not time_limits.clear_limit(db, step_name, repository_id):
        raise error(404, "no such override to clear", code="NOT_FOUND")
    db.commit()
    return _list(db)
