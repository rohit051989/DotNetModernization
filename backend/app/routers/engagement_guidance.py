"""Engagement guidance (36-COPILOT-ENHANCED-CONVERSION "Engagement guidance", 2026-11-26): what one engagement adds to
the master catalog's engine guidance, never a fork of it.

- A note on a resolution: carried after the master guidance in the engagement's work items, under "For this
  engagement:", taking precedence where the two conflict. The master text keeps reaching the engagement as it changes.
- The engagement's conventions (logging, naming, error format and the like): carried in the top-level instructions of
  every conversion of its repositories, for both engines; the design questions never ask about what they decide.

Both are engagement data (rule 6), written only to engagement_resolution_notes and engagements.conventions, never to
the master catalog (rule 9). Admins edit them (app.auth.policy: not named, so admins only), with a version check
(app.auth.versions); each edit is recorded with who and from which machine (app.auth.activity, by the HTTP guard). Each
passes the self-containedness and secret checks when saved (app.items.engine_text).
"""
import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import models
from app.auth import activity, versions
from app.auth import actor as actors
from app.db import get_db
from app.errors import ErrorResponse, error
from app.items import engine_text

router = APIRouter(prefix="/api/engagements", tags=["Engagement guidance"])

_IF_MATCH = "The version of the copy edited (0 when there was none yet); a stale copy is refused (409 STALE_COPY)."


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resolution_id: str
    item_id: str
    note: str | None = Field(description="The engagement's note, carried after the master guidance. Null: none.")
    version: int = Field(description="Send it in If-Match with an edit; 0 when no note was ever saved.")
    updated_by: str | None
    updated_at: datetime.datetime | None


class NoteWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(description="What this engagement adds to the resolution's master guidance; empty clears it.")


class ConventionsOut(BaseModel):
    conventions: str | None = Field(description="The engagement's conventions, carried in every conversion's instructions.")
    version: int = Field(description="The engagement's settings version: send it in If-Match with an edit.")


class ConventionsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conventions: str | None = Field(description="Logging, naming, error format and the like; empty clears them.")


def _engagement(db: Session, engagement_id: str, lock: bool = False) -> models.Engagement:
    engagement = versions.locked(db, models.Engagement, engagement_id) if lock else db.get(models.Engagement, engagement_id)
    if engagement is None or engagement.deleted_at is not None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    return engagement


def _clean(text: str | None) -> str | None:
    return (text or "").strip().replace("\r\n", "\n") or None


@router.get("/{engagement_id}/resolution-notes", response_model=list[NoteOut], operation_id="list_resolution_notes",
            summary="List an engagement's notes on catalog resolutions", responses={404: {"model": ErrorResponse}})
def list_notes(engagement_id: str, db: Session = Depends(get_db)):
    _engagement(db, engagement_id)
    rows = (db.query(models.EngagementResolutionNote, models.ItemResolution.item_id)
            .join(models.ItemResolution, models.ItemResolution.id == models.EngagementResolutionNote.resolution_id)
            .filter(models.EngagementResolutionNote.engagement_id == engagement_id)
            .order_by(models.ItemResolution.item_id, models.EngagementResolutionNote.resolution_id).all())
    return [NoteOut(resolution_id=n.resolution_id, item_id=item_id, note=n.note, version=n.version,
                    updated_by=n.updated_by, updated_at=n.updated_at) for n, item_id in rows]


@router.put("/{engagement_id}/resolutions/{resolution_id}/note", response_model=NoteOut, operation_id="put_resolution_note",
            summary="Set an engagement's note on a catalog resolution",
            responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse},
                       428: {"model": ErrorResponse}})
def put_note(engagement_id: str, resolution_id: str, payload: NoteWrite, db: Session = Depends(get_db),
             if_match: Annotated[str | None, Header(description=_IF_MATCH)] = None):
    _engagement(db, engagement_id)
    resolution = db.get(models.ItemResolution, resolution_id)
    if resolution is None or resolution.deleted_at is not None:
        raise error(404, f"Resolution '{resolution_id}' not found", code="NOT_FOUND")
    activity.about("engagement_resolution_note", f"{engagement_id}/{resolution_id}")
    row = versions.locked(db, models.EngagementResolutionNote, (engagement_id, resolution_id))
    versions.check(db, row.version if row else None, if_match, "engagement_resolution_note",
                   f"{engagement_id}/{resolution_id}", f"this engagement's note on '{resolution.name}'")
    note = _clean(payload.note)
    engine_text.check(db, "note", note, "engagement note")
    person = actors.current()
    if row is None:
        row = models.EngagementResolutionNote(engagement_id=engagement_id, resolution_id=resolution_id, version=1)
        db.add(row)
    else:
        row.version += 1
    row.note = note
    row.updated_by = person.label() if person else None
    row.updated_at = datetime.datetime.now(datetime.timezone.utc)
    activity.record(db, "engagement_note.edit", "engagement_resolution_note", f"{engagement_id}/{resolution_id}",
                    f"{'Set' if note else 'Cleared'} the engagement's note on {resolution.item_id} / {resolution_id}")
    db.commit()
    db.refresh(row)
    return NoteOut(resolution_id=row.resolution_id, item_id=resolution.item_id, note=row.note, version=row.version,
                   updated_by=row.updated_by, updated_at=row.updated_at)


@router.get("/{engagement_id}/conventions", response_model=ConventionsOut, operation_id="get_engagement_conventions",
            summary="Get an engagement's conventions", responses={404: {"model": ErrorResponse}})
def get_conventions(engagement_id: str, db: Session = Depends(get_db)):
    engagement = _engagement(db, engagement_id)
    return ConventionsOut(conventions=engagement.conventions, version=engagement.version)


@router.put("/{engagement_id}/conventions", response_model=ConventionsOut, operation_id="put_engagement_conventions",
            summary="Set an engagement's conventions",
            responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse},
                       428: {"model": ErrorResponse}})
def put_conventions(engagement_id: str, payload: ConventionsWrite, db: Session = Depends(get_db),
                    if_match: Annotated[str | None, Header(description=_IF_MATCH)] = None):
    engagement = _engagement(db, engagement_id, lock=True)
    versions.check(db, engagement.version, if_match, "engagement", engagement_id, "this engagement's conventions")
    conventions = _clean(payload.conventions)
    engine_text.check(db, "conventions", conventions, "engagement's conventions")
    engagement.conventions = conventions
    engagement.version += 1
    engagement.updated_at = datetime.datetime.now(datetime.timezone.utc)
    activity.record(db, "engagement_conventions.edit", "engagement", engagement_id,
                    f"{'Set' if conventions else 'Cleared'} the engagement's conventions")
    db.commit()
    db.refresh(engagement)
    return ConventionsOut(conventions=engagement.conventions, version=engagement.version)
