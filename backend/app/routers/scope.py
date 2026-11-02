"""A repository's conversion scope (36-COPILOT-ENHANCED-CONVERSION.md Part O; app.scope): which of its projects its
conversions cover, read by everyone and saved by its owner or an admin, from the machine it was registered on.

Saving a changed scope prepares again a conversion that has not been run yet (the same discovery run a rescan
starts, which refreshes it in place). A conversion already run keeps the scope it was prepared with; the new scope
applies to the next one.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ErrorResponse
from app.scope import service

router = APIRouter(prefix="/api", tags=["Conversion scope"])

_NOT_FOUND = {"model": ErrorResponse, "description": "No repository exists with this id."}


class ScopeProjectOut(BaseModel):
    path: str = Field(description="Relative to the repository: the project's identity in the scope.")
    name: str
    solutions: list[str] = Field(description="The solutions that contain it.")
    dependsOn: list[str] = Field(description="The projects it references (solution-discovery's project references).")
    workItems: int = Field(description="Work items found in it, counted as the work list counts them.")
    excluded: bool
    new: bool = Field(description="Discovered after the scope was saved: in scope by default.")


class ScopeSolutionOut(BaseModel):
    path: str
    name: str
    projects: list[str]


class ScopeSavedOut(BaseModel):
    by: str
    on: str | None = None
    at: str
    reason: str | None = None


class ScopeTotalsOut(BaseModel):
    projects: int
    kept: int
    excluded: int
    workItemsOutOfScope: int
    new: int


class NextConversionScopeOut(BaseModel):
    """What saving now does to the conversions."""
    reprepares: int | None = Field(None, description="The conversion a save prepares again: the latest, not run yet.")
    keeps: int | None = Field(None, description="The latest conversion, already run: it keeps the scope it was prepared with.")
    note: str


class ScopeOut(BaseModel):
    version: int = Field(description="0 when no scope was ever saved: every project is in scope.")
    saved: ScopeSavedOut | None = None
    treatment: str
    solutions: list[ScopeSolutionOut]
    projects: list[ScopeProjectOut]
    gone: list[str] = Field(description="Excluded at the last save, no longer in the repository: dropped out.")
    totals: ScopeTotalsOut
    on_save: NextConversionScopeOut


class ScopeIn(BaseModel):
    excluded: list[str] = Field(description="Every project left out, by path. Everything else is kept.")
    reason: str | None = Field(None, max_length=2000)


class ScopeSavedResultOut(BaseModel):
    version: int
    newlyExcluded: list[str]
    reIncluded: list[str]
    reprepare_job_execution_id: str | None = None
    note: str


def _on_save(db: Session, repository) -> NextConversionScopeOut:
    from app.routers import conversion

    snapshot, _ = conversion._snapshot(db, repository)
    latest = (snapshot.get("entries") or [None])[0]
    if latest is None:
        return NextConversionScopeOut(note="No conversion yet: the first one is prepared with this scope.")
    if latest["state"] == "prepared":
        return NextConversionScopeOut(reprepares=latest["number"],
                                      note=f"Saving prepares conversion {latest['number']} again (it has not been run "
                                           "yet), with this scope.")
    return NextConversionScopeOut(keeps=latest["number"],
                                  note=f"Conversion {latest['number']} has been run: it keeps the scope it was prepared "
                                       "with. The new scope applies to the next one.")


@router.get(
    "/repositories/{repository_id}/scope",
    response_model=ScopeOut,
    summary="The repository's conversion scope: its solutions and projects, which are excluded, and the totals",
    operation_id="get_conversion_scope",
    responses={404: _NOT_FOUND},
)
def get_scope(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    repository = service.repository_or_404(db, repository_id)
    return ScopeOut(**service.tree(db, repository), on_save=_on_save(db, repository))


@router.put(
    "/repositories/{repository_id}/scope",
    response_model=ScopeSavedResultOut,
    summary="Save the repository's conversion scope",
    operation_id="save_conversion_scope",
    responses={404: _NOT_FOUND,
               409: {"model": ErrorResponse, "description": "Someone else saved the scope first (STALE_COPY)."},
               422: {"model": ErrorResponse, "description": "Every problem with the selection (SCOPE_INVALID), together."},
               428: {"model": ErrorResponse, "description": "The save names no version (VERSION_REQUIRED)."}},
)
def save_scope(
    repository_id: uuid.UUID, payload: ScopeIn, background_tasks: BackgroundTasks, db: Session = Depends(get_db),
    if_match: Annotated[str | None, Header(description="The scope's version the edit was made on (0 when none was "
                                                       "saved yet); a stale copy is refused (409 STALE_COPY).")] = None,
):
    from app.repositories import service as repositories
    from app.routers import conversion

    repository = service.repository_or_404(db, repository_id)
    on_save = _on_save(db, repository)
    saved = service.save(db, repository, payload.excluded, payload.reason, if_match)
    changed = bool(saved["newlyExcluded"] or saved["reIncluded"])
    job = None
    if changed and on_save.reprepares is not None:
        token = repositories.start_rescan(repository)
        job = conversion._launch(db, background_tasks, conversion._DISCOVERY_JOB, {
            "engagement_id": repository.engagement_id, "repository_id": str(repository.id), "ingest_token": token,
            "prepare_conversion": True})
        note = f"Saved. Conversion {on_save.reprepares} is being prepared again with this scope."
    elif not changed:
        note = "Saved: the same projects as before, so no conversion changes."
    else:
        note = "Saved. " + on_save.note.replace("Saving prepares", "The next preparation prepares")
    return ScopeSavedResultOut(**saved, reprepare_job_execution_id=job, note=note)
