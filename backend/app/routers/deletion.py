"""Hard delete of a repository or an engagement (app.deletion.service; docs/VDI-SETUP.md section O).

GET shows exactly what would go. POST deletes it, given the name typed to confirm; the plan is made again at that
moment, never taken from the request. Refused (409) while a job of it runs, or when the typed name does not match;
409 too when files could not be removed, in which case nothing was deleted from the database.

TODO: gate behind an admin check once auth exists (04-FRONTEND-SPEC.md, "Future: access control").
"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.deletion import service
from app.errors import ErrorResponse, error

router = APIRouter(prefix="/api", tags=["Deletion"])

_REFUSED = {409: {"model": ErrorResponse, "description": "Refused: a job is running, the typed name does not match, or "
                                                          "files could not be removed (nothing deleted)."}}


class ConfirmIn(BaseModel):
    confirm: str


class DeletionAuditOut(BaseModel):
    deleted_at: str
    deleted_by: str
    via: str
    kind: str
    engagement_id: str
    repository_slug: str | None
    name: str
    summary: dict


def _repository(db: Session, repository_id: uuid.UUID) -> models.Repository:
    repo = db.get(models.Repository, repository_id)          # a soft-deleted one too: hard delete clears it away
    if repo is None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")
    return repo


def _engagement(db: Session, engagement_id: str) -> models.Engagement:
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    return engagement


def _delete(db: Session, plan: dict, typed: str) -> dict:
    try:
        return service.delete(db, plan, typed, via="ui")
    except service.DeletionRefused as e:
        raise error(409, str(e), field="confirm", code="DELETE_REFUSED")
    except service.DeletionIncomplete as e:
        raise error(409, str(e), code="DELETE_INCOMPLETE")


@router.get("/repositories/{repository_id}/deletion", summary="What a hard delete of the repository would remove",
            operation_id="repository_deletion_plan", responses={404: {"model": ErrorResponse}})
def repository_deletion_plan(repository_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    return service.public(service.repository_plan(db, _repository(db, repository_id)))


@router.post("/repositories/{repository_id}/deletion", summary="Hard delete the repository from its engagement",
             operation_id="delete_repository_hard", responses={404: {"model": ErrorResponse}, **_REFUSED})
def delete_repository_hard(repository_id: uuid.UUID, body: ConfirmIn, db: Session = Depends(get_db)) -> dict:
    return _delete(db, service.repository_plan(db, _repository(db, repository_id)), body.confirm)


@router.get("/engagements/{engagement_id}/deletion", summary="What a hard delete of the engagement would remove",
            operation_id="engagement_deletion_plan", responses={404: {"model": ErrorResponse}})
def engagement_deletion_plan(engagement_id: str, db: Session = Depends(get_db)) -> dict:
    return service.public(service.engagement_plan(db, _engagement(db, engagement_id)))


@router.post("/engagements/{engagement_id}/deletion", summary="Hard delete the engagement and all its repositories",
             operation_id="delete_engagement_hard", responses={404: {"model": ErrorResponse}, **_REFUSED})
def delete_engagement_hard(engagement_id: str, body: ConfirmIn, db: Session = Depends(get_db)) -> dict:
    return _delete(db, service.engagement_plan(db, _engagement(db, engagement_id)), body.confirm)


@router.get("/deletions", response_model=list[DeletionAuditOut], summary="Every hard delete made: what, by whom, when",
            operation_id="list_deletions")
def list_deletions(db: Session = Depends(get_db)):
    return [DeletionAuditOut(deleted_at=a.deleted_at.isoformat(), deleted_by=a.deleted_by, via=a.via, kind=a.kind,
                             engagement_id=a.engagement_id, repository_slug=a.repository_slug, name=a.name,
                             summary=a.summary)
            for a in db.query(models.DeletionAudit).order_by(models.DeletionAudit.deleted_at.desc())]
