import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_db
from app.routers.target_states import get_target_states_for_pattern

router = APIRouter(prefix="/api/engagements", tags=["engagement-patterns"])


def _get_engagement(db: Session, engagement_id: str) -> models.Engagement:
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None or engagement.deleted_at is not None:
        raise HTTPException(status_code=404, detail=f"Engagement '{engagement_id}' not found")
    return engagement


def _get_visible_master_pattern(db: Session, pattern_id: str) -> models.Pattern:
    """Master-deleted patterns are invisible to every client-scoped operation,
    unconditionally — there is no include_deleted override for this, since that
    flag only ever governs the overlay's own (client-scoped) deletion state."""
    pattern = db.get(models.Pattern, pattern_id)
    if pattern is None or pattern.deleted_at is not None:
        raise HTTPException(status_code=404, detail=f"Pattern '{pattern_id}' not found")
    return pattern


def _get_overlay(
    db: Session, engagement_id: str, pattern_id: str
) -> models.EngagementPattern | None:
    return db.get(models.EngagementPattern, (engagement_id, pattern_id))


def _get_or_create_overlay(
    db: Session, engagement_id: str, pattern_id: str
) -> models.EngagementPattern:
    overlay = _get_overlay(db, engagement_id, pattern_id)
    if overlay is None:
        overlay = models.EngagementPattern(engagement_id=engagement_id, pattern_id=pattern_id)
        db.add(overlay)
    return overlay


def _decision_summary(
    db: Session, engagement_id: str, pattern_id: str
) -> tuple[str | None, str | None]:
    decision = (
        db.query(models.DecisionRecord)
        .filter(
            models.DecisionRecord.engagement_id == engagement_id,
            models.DecisionRecord.pattern_id == pattern_id,
            models.DecisionRecord.status != "superseded",
            models.DecisionRecord.deleted_at.is_(None),
        )
        .first()
    )
    if decision is None:
        return None, None

    selected_target_state_name = None
    if decision.selected_target_state_id:
        target_state = db.get(models.TargetStateOption, decision.selected_target_state_id)
        selected_target_state_name = target_state.name if target_state else None
    return decision.status, selected_target_state_name


def _to_view(
    db: Session,
    pattern: models.Pattern,
    overlay: models.EngagementPattern | None,
    engagement_id: str,
) -> schemas.EngagementPatternView:
    decision_status, selected_target_state_name = _decision_summary(db, engagement_id, pattern.id)
    options = get_target_states_for_pattern(db, pattern.id)
    return schemas.EngagementPatternView(
        engagement_id=engagement_id,
        pattern_id=pattern.id,
        name=pattern.name,
        summary=pattern.summary,
        description=pattern.description,
        legacy_stack=pattern.legacy_stack,
        category=pattern.category,
        detection_rules=pattern.detection_rules,
        typical_indicators=pattern.typical_indicators,
        known_risks=pattern.known_risks,
        status=pattern.status,
        version=pattern.version,
        created_at=pattern.created_at,
        updated_at=pattern.updated_at,
        target_state_options=[schemas.TargetStateSummary.model_validate(o) for o in options],
        scope_status=overlay.scope_status if overlay else "active",
        deferred_reason=overlay.deferred_reason if overlay else None,
        deleted_at=overlay.deleted_at if overlay else None,
        deleted_by=overlay.deleted_by if overlay else None,
        decision_status=decision_status,
        selected_target_state_name=selected_target_state_name,
    )


@router.get("/{engagement_id}/patterns", response_model=list[schemas.EngagementPatternView])
def list_engagement_patterns(
    engagement_id: str,
    include_deleted: bool = Query(False),
    include_deferred: bool = Query(True),
    db: Session = Depends(get_db),
):
    _get_engagement(db, engagement_id)

    patterns = (
        db.query(models.Pattern)
        .filter(models.Pattern.deleted_at.is_(None))
        .order_by(models.Pattern.id)
        .all()
    )

    overlays = {
        overlay.pattern_id: overlay
        for overlay in db.query(models.EngagementPattern)
        .filter(models.EngagementPattern.engagement_id == engagement_id)
        .all()
    }

    results = []
    for pattern in patterns:
        overlay = overlays.get(pattern.id)
        if overlay is not None and overlay.deleted_at is not None and not include_deleted:
            continue
        if overlay is not None and overlay.scope_status == "deferred" and not include_deferred:
            continue
        results.append(_to_view(db, pattern, overlay, engagement_id))
    return results


@router.get(
    "/{engagement_id}/patterns/{pattern_id}", response_model=schemas.EngagementPatternView
)
def get_engagement_pattern(
    engagement_id: str,
    pattern_id: str,
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
):
    _get_engagement(db, engagement_id)
    pattern = _get_visible_master_pattern(db, pattern_id)

    overlay = _get_overlay(db, engagement_id, pattern_id)
    if overlay is not None and overlay.deleted_at is not None and not include_deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Pattern '{pattern_id}' not found in engagement '{engagement_id}'",
        )
    return _to_view(db, pattern, overlay, engagement_id)


@router.post(
    "/{engagement_id}/patterns/{pattern_id}/defer", response_model=schemas.EngagementPatternView
)
def defer_engagement_pattern(
    engagement_id: str,
    pattern_id: str,
    payload: schemas.EngagementPatternDeferRequest,
    db: Session = Depends(get_db),
):
    _get_engagement(db, engagement_id)
    pattern = _get_visible_master_pattern(db, pattern_id)

    overlay = _get_or_create_overlay(db, engagement_id, pattern_id)
    overlay.scope_status = "deferred"
    overlay.deferred_reason = payload.deferred_reason
    overlay.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    return _to_view(db, pattern, overlay, engagement_id)


@router.post(
    "/{engagement_id}/patterns/{pattern_id}/reactivate",
    response_model=schemas.EngagementPatternView,
)
def reactivate_engagement_pattern(
    engagement_id: str, pattern_id: str, db: Session = Depends(get_db)
):
    _get_engagement(db, engagement_id)
    pattern = _get_visible_master_pattern(db, pattern_id)

    overlay = _get_or_create_overlay(db, engagement_id, pattern_id)
    overlay.scope_status = "active"
    overlay.deferred_reason = None
    overlay.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    return _to_view(db, pattern, overlay, engagement_id)


@router.delete(
    "/{engagement_id}/patterns/{pattern_id}",
    response_model=schemas.EngagementPatternSoftDeleteResponse,
)
def delete_engagement_pattern(
    engagement_id: str,
    pattern_id: str,
    deleted_by: str | None = Query(None),
    db: Session = Depends(get_db),
):
    _get_engagement(db, engagement_id)
    _get_visible_master_pattern(db, pattern_id)

    live_decision = (
        db.query(models.DecisionRecord)
        .filter(
            models.DecisionRecord.engagement_id == engagement_id,
            models.DecisionRecord.pattern_id == pattern_id,
            models.DecisionRecord.status != "superseded",
            models.DecisionRecord.deleted_at.is_(None),
        )
        .first()
    )
    if live_decision is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Engagement '{engagement_id}' has a non-superseded decision record "
                f"'{live_decision.id}' for pattern '{pattern_id}'; supersede or remove it first."
            ),
        )

    overlay = _get_or_create_overlay(db, engagement_id, pattern_id)
    now = datetime.datetime.now(datetime.timezone.utc)
    overlay.deleted_at = now
    overlay.deleted_by = deleted_by
    overlay.updated_at = now
    db.commit()
    return schemas.EngagementPatternSoftDeleteResponse(
        engagement_id=engagement_id, pattern_id=pattern_id, deleted_at=now
    )


@router.post(
    "/{engagement_id}/patterns/{pattern_id}/restore",
    response_model=schemas.EngagementPatternSoftDeleteResponse,
)
def restore_engagement_pattern(engagement_id: str, pattern_id: str, db: Session = Depends(get_db)):
    # Admin-only in intent — no auth/role check exists yet in this build (see
    # CLAUDE.md's out-of-scope list). TODO: gate behind an admin role once auth exists.
    _get_engagement(db, engagement_id)
    pattern = db.get(models.Pattern, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail=f"Pattern '{pattern_id}' not found")

    overlay = _get_overlay(db, engagement_id, pattern_id)
    if overlay is not None:
        overlay.deleted_at = None
        overlay.deleted_by = None
        overlay.updated_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()

    return schemas.EngagementPatternSoftDeleteResponse(
        engagement_id=engagement_id, pattern_id=pattern_id, deleted_at=None
    )
