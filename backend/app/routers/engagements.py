import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_db

router = APIRouter(prefix="/api/engagements", tags=["engagements"])


@router.get("", response_model=list[schemas.Engagement])
def list_engagements(include_deleted: bool = Query(False), db: Session = Depends(get_db)):
    query = db.query(models.Engagement)
    if not include_deleted:
        query = query.filter(models.Engagement.deleted_at.is_(None))
    return query.order_by(models.Engagement.id).all()


@router.post("", response_model=schemas.Engagement, status_code=201)
def create_engagement(payload: schemas.EngagementCreate, db: Session = Depends(get_db)):
    if db.get(models.Engagement, payload.id) is not None:
        raise HTTPException(status_code=409, detail=f"Engagement '{payload.id}' already exists")

    engagement = models.Engagement(
        id=payload.id,
        client_name=payload.client_name,
        description=payload.description,
        target_platform=payload.target_platform,
        default_posture=payload.default_posture,
    )
    db.add(engagement)
    db.commit()
    db.refresh(engagement)
    return engagement


@router.get("/{engagement_id}", response_model=schemas.Engagement)
def get_engagement(
    engagement_id: str, include_deleted: bool = Query(False), db: Session = Depends(get_db)
):
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None or (engagement.deleted_at is not None and not include_deleted):
        raise HTTPException(status_code=404, detail=f"Engagement '{engagement_id}' not found")
    return engagement


@router.put("/{engagement_id}", response_model=schemas.Engagement)
def update_engagement(
    engagement_id: str, payload: schemas.EngagementUpdate, db: Session = Depends(get_db)
):
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None:
        raise HTTPException(status_code=404, detail=f"Engagement '{engagement_id}' not found")

    engagement.client_name = payload.client_name
    engagement.description = payload.description
    engagement.target_platform = payload.target_platform
    engagement.default_posture = payload.default_posture
    if payload.status is not None:
        engagement.status = payload.status
    engagement.updated_at = datetime.datetime.now(datetime.timezone.utc)

    db.commit()
    db.refresh(engagement)
    return engagement


@router.get("/{engagement_id}/coverage", response_model=schemas.CoverageSummary)
def get_engagement_coverage(engagement_id: str, db: Session = Depends(get_db)):
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None:
        raise HTTPException(status_code=404, detail=f"Engagement '{engagement_id}' not found")

    active_pattern_ids = {
        p.id
        for p in db.query(models.Pattern.id)
        .filter(models.Pattern.status == "active", models.Pattern.deleted_at.is_(None))
        .all()
    }

    overlays = {
        overlay.pattern_id: overlay
        for overlay in db.query(models.EngagementPattern)
        .filter(models.EngagementPattern.engagement_id == engagement_id)
        .all()
    }

    # Client-deleted patterns don't count toward this engagement's coverage at all.
    client_deleted_pattern_ids = {
        pid for pid, overlay in overlays.items() if overlay.deleted_at is not None
    }
    counted_pattern_ids = active_pattern_ids - client_deleted_pattern_ids

    deferred_pattern_ids = {
        pid
        for pid, overlay in overlays.items()
        if overlay.scope_status == "deferred" and overlay.deleted_at is None
    } & counted_pattern_ids

    live_decisions = (
        db.query(models.DecisionRecord)
        .filter(
            models.DecisionRecord.engagement_id == engagement_id,
            models.DecisionRecord.status != "superseded",
            models.DecisionRecord.deleted_at.is_(None),
        )
        .all()
    )
    decisions_by_pattern = {d.pattern_id: d for d in live_decisions}

    approved = sum(
        1 for d in live_decisions if d.status == "approved" and d.pattern_id in counted_pattern_ids
    )
    in_review = sum(
        1 for d in live_decisions if d.status == "in_review" and d.pattern_id in counted_pattern_ids
    )
    parked = sum(
        1 for d in live_decisions if d.status == "parked" and d.pattern_id in counted_pattern_ids
    )

    # Genuinely untouched: no decision, and no overlay row at all (not even deferred).
    patterns_without_decision = sorted(
        pid for pid in counted_pattern_ids if pid not in decisions_by_pattern and pid not in overlays
    )

    return schemas.CoverageSummary(
        engagement_id=engagement_id,
        total_patterns=len(counted_pattern_ids),
        approved=approved,
        in_review=in_review,
        parked=parked,
        deferred=len(deferred_pattern_ids),
        patterns_without_decision=patterns_without_decision,
    )
