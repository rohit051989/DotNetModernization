"""Engagement decisions on catalog items — 28-ITEM-AND-CONVERSION-MODEL.md
Part F.

Client-scoped: these routes write `engagement_decisions` only, never
`catalog_items` or `item_resolutions` (CLAUDE.md rule 9). One live decision
per (engagement, item); superseding frees the slot and keeps the history.

Validation carried over from the pattern decision records: approval needs a
resolution belonging to the item, a rationale, an approver and a date; and
choosing anything but the lowest `consumer_impact` needs the
`forcing_perspective` / `forcing_rationale` pair (25-STANDARDS-AND-VIEWPOINTS.md
A1). One change from the pattern records: "lowest" is judged across the
item's whole live resolution menu, not `candidates_considered`, which is kept
only as a record of what was presented at decision time.
"""

import datetime
import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error, errors
from app.items import schemas as item_schemas
from app.schemas import CONSUMER_IMPACT_RANK

router = APIRouter(prefix="/api", tags=["Item Decisions"])

_VALIDATION_FAILED = {"model": ErrorResponse, "description": "A decision validation rule failed."}

# Substrings of `engagements.target_platform` that mean the engagement lands
# on Linux. Free text today, so this is a heuristic; "Azure Kubernetes
# Service" is deliberately absent because AKS also runs Windows node pools.
_LINUX_PLATFORM_MARKERS = ("linux", "openshift", "ocp")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def targets_linux(engagement: models.Engagement) -> bool:
    platform = (engagement.target_platform or "").lower()
    return any(marker in platform for marker in _LINUX_PLATFORM_MARKERS)


def _live_resolutions(db: Session, item_id: str) -> list[models.ItemResolution]:
    return (
        db.query(models.ItemResolution)
        .filter(
            models.ItemResolution.item_id == item_id,
            models.ItemResolution.deleted_at.is_(None),
            models.ItemResolution.status == "active",
        )
        .all()
    )


def decision_warnings(db: Session, decision: models.EngagementDecision) -> list[str]:
    if not decision.resolution_id:
        return []
    resolution = db.get(models.ItemResolution, decision.resolution_id)
    engagement = db.get(models.Engagement, decision.engagement_id)
    if resolution is not None and not resolution.linux_compatible and targets_linux(engagement):
        return [
            f"Resolution '{resolution.name}' is not Linux-compatible, but this engagement targets "
            f"'{engagement.target_platform}'."
        ]
    return []


def _response(db: Session, decision: models.EngagementDecision) -> item_schemas.EngagementDecisionOut:
    item = db.get(models.CatalogItem, decision.item_id)
    resolution = db.get(models.ItemResolution, decision.resolution_id) if decision.resolution_id else None
    return item_schemas.EngagementDecisionOut(
        id=str(decision.id),
        engagement_id=decision.engagement_id,
        item_id=decision.item_id,
        item_name=item.name if item else decision.item_id,
        resolution_id=decision.resolution_id,
        resolution_name=resolution.name if resolution else None,
        candidates_considered=decision.candidates_considered,
        rationale=decision.rationale,
        forcing_perspective=decision.forcing_perspective,
        forcing_rationale=decision.forcing_rationale,
        evaluation_notes=decision.evaluation_notes,
        approver_name=decision.approver_name,
        approver_role=decision.approver_role,
        decision_date=decision.decision_date,
        status=decision.status,
        warnings=decision_warnings(db, decision),
        created_at=decision.created_at,
        updated_at=decision.updated_at,
    )


def validate_decision(db: Session, item_id: str, decision: models.EngagementDecision) -> None:
    """Checks the decision's would-be state (after the payload is applied)."""
    problems: list[dict] = []

    resolution = None
    if decision.resolution_id:
        resolution = db.get(models.ItemResolution, decision.resolution_id)
        if resolution is None or resolution.deleted_at is not None:
            problems.append(
                {
                    "field": "resolution_id",
                    "message": f"Resolution '{decision.resolution_id}' does not exist.",
                    "code": "RESOLUTION_NOT_FOUND",
                }
            )
            resolution = None
        elif resolution.item_id != item_id:
            problems.append(
                {
                    "field": "resolution_id",
                    "message": f"Resolution '{resolution.id}' belongs to item '{resolution.item_id}', not '{item_id}'.",
                    "code": "RESOLUTION_WRONG_ITEM",
                }
            )
            resolution = None

    if decision.status == "approved":
        for field, code, what in (
            ("resolution_id", "APPROVAL_REQUIRES_SELECTION", "a selected resolution"),
            ("rationale", "APPROVAL_REQUIRES_RATIONALE", "a rationale"),
            ("approver_name", "APPROVAL_REQUIRES_APPROVER", "an approver name"),
            ("decision_date", "APPROVAL_REQUIRES_DATE", "a decision date"),
        ):
            if not getattr(decision, field):
                problems.append({"field": field, "message": f"An approved decision requires {what}.", "code": code})

        menu = _live_resolutions(db, item_id)
        if resolution is not None and menu:
            lowest = min(menu, key=lambda r: CONSUMER_IMPACT_RANK[r.consumer_impact])
            if CONSUMER_IMPACT_RANK[resolution.consumer_impact] > CONSUMER_IMPACT_RANK[lowest.consumer_impact]:
                message = (
                    f"{resolution.name} has higher consumer impact ({resolution.consumer_impact}) than the "
                    f"lowest option {lowest.name} ({lowest.consumer_impact}). Both forcing_perspective and "
                    "forcing_rationale are required to justify the deviation."
                )
                problems += [
                    {"field": field, "message": message, "code": "FORCING_PERSPECTIVE_AND_RATIONALE_REQUIRED"}
                    for field in ("forcing_perspective", "forcing_rationale")
                    if not getattr(decision, field)
                ]

    if problems:
        raise errors(422, problems)


def _live_decision(db: Session, engagement_id: str, item_id: str) -> models.EngagementDecision | None:
    return (
        db.query(models.EngagementDecision)
        .filter(
            models.EngagementDecision.engagement_id == engagement_id,
            models.EngagementDecision.item_id == item_id,
            models.EngagementDecision.status != "superseded",
        )
        .first()
    )


@router.get(
    "/engagements/{engagement_id}/item-decisions",
    response_model=list[item_schemas.EngagementDecisionOut],
    summary="List an engagement's item decisions",
    operation_id="list_engagement_item_decisions",
    responses={404: {"model": ErrorResponse, "description": "No engagement exists with this id."}},
)
def list_item_decisions(engagement_id: str, db: Session = Depends(get_db)):
    if db.get(models.Engagement, engagement_id) is None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    decisions = (
        db.query(models.EngagementDecision)
        .filter(models.EngagementDecision.engagement_id == engagement_id)
        .order_by(models.EngagementDecision.item_id, models.EngagementDecision.created_at)
        .all()
    )
    return [_response(db, d) for d in decisions]


@router.get(
    "/engagements/{engagement_id}/items/{item_id}/decision",
    response_model=item_schemas.EngagementDecisionOut,
    summary="Get the live decision for an item in an engagement",
    operation_id="get_engagement_item_decision",
    responses={404: {"model": ErrorResponse, "description": "No live decision for this (engagement, item) pair."}},
)
def get_item_decision(engagement_id: str, item_id: str, db: Session = Depends(get_db)):
    decision = _live_decision(db, engagement_id, item_id)
    if decision is None:
        raise error(404, f"No live decision for item '{item_id}' in engagement '{engagement_id}'", code="NOT_FOUND")
    return _response(db, decision)


@router.put(
    "/engagements/{engagement_id}/items/{item_id}/decision",
    response_model=item_schemas.EngagementDecisionOut,
    summary="Record or update the decision for an item in an engagement",
    operation_id="upsert_engagement_item_decision",
    responses={
        404: {"model": ErrorResponse, "description": "No engagement or item exists with these ids."},
        422: _VALIDATION_FAILED,
    },
)
def upsert_item_decision(
    engagement_id: str,
    item_id: str,
    payload: item_schemas.EngagementDecisionUpsert,
    response: Response,
    db: Session = Depends(get_db),
):
    """Creates the live decision (201) or updates it in place (200). An
    omitted field keeps its current value. A Linux-incompatible resolution
    on a Linux-targeted engagement is allowed, and reported in `warnings`."""
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    item = db.get(models.CatalogItem, item_id)
    if item is None or item.deleted_at is not None:
        raise error(404, f"Catalog item '{item_id}' not found", code="NOT_FOUND")

    decision = _live_decision(db, engagement_id, item_id)
    created = decision is None
    if created:
        decision = models.EngagementDecision(
            id=uuid.uuid4(), engagement_id=engagement_id, item_id=item_id, status="pending"
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(decision, field, value)

    # Validate before the row joins the session, so a rejected create
    # leaves nothing behind to autoflush.
    validate_decision(db, item_id, decision)
    decision.updated_at = _now()
    if created:
        db.add(decision)
        response.status_code = 201
    db.commit()
    db.refresh(decision)
    return _response(db, decision)


@router.post(
    "/item-decisions/{decision_id}/supersede",
    response_model=item_schemas.EngagementDecisionOut,
    summary="Supersede an item decision",
    operation_id="supersede_item_decision",
    responses={404: {"model": ErrorResponse, "description": "No decision exists with this id."}},
)
def supersede_item_decision(decision_id: uuid.UUID, db: Session = Depends(get_db)):
    decision = db.get(models.EngagementDecision, decision_id)
    if decision is None:
        raise error(404, f"Decision '{decision_id}' not found", code="NOT_FOUND")
    decision.status = "superseded"
    decision.updated_at = _now()
    db.commit()
    db.refresh(decision)
    return _response(db, decision)
