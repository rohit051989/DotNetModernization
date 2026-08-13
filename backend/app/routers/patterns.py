import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_db
from app.routers.target_states import get_target_states_for_pattern

router = APIRouter(prefix="/api/patterns", tags=["patterns"])


def _pattern_detail(db: Session, pattern: models.Pattern) -> schemas.PatternDetail:
    options = get_target_states_for_pattern(db, pattern.id)
    return schemas.PatternDetail(
        id=pattern.id,
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
        target_state_options=[
            schemas.TargetStateSummary.model_validate(option) for option in options
        ],
    )


@router.get("", response_model=list[schemas.PatternSummary])
def list_patterns(
    status: str | None = None,
    category: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Pattern)
    if status:
        query = query.filter(models.Pattern.status == status)
    if category:
        query = query.filter(models.Pattern.category == category)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                models.Pattern.name.ilike(like),
                models.Pattern.summary.ilike(like),
                models.Pattern.legacy_stack.ilike(like),
            )
        )
    patterns = query.order_by(models.Pattern.id).all()

    counts = dict(
        db.query(models.TargetStateOption.pattern_id, func.count(models.TargetStateOption.id))
        .filter(models.TargetStateOption.status != "deprecated")
        .group_by(models.TargetStateOption.pattern_id)
        .all()
    )

    return [
        schemas.PatternSummary(
            id=p.id,
            name=p.name,
            summary=p.summary,
            legacy_stack=p.legacy_stack,
            category=p.category,
            status=p.status,
            version=p.version,
            target_state_count=counts.get(p.id, 0),
            updated_at=p.updated_at,
        )
        for p in patterns
    ]


@router.get("/{pattern_id}", response_model=schemas.PatternDetail)
def get_pattern(pattern_id: str, db: Session = Depends(get_db)):
    pattern = db.get(models.Pattern, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail=f"Pattern '{pattern_id}' not found")
    return _pattern_detail(db, pattern)


@router.post("", response_model=schemas.PatternDetail, status_code=201)
def create_pattern(payload: schemas.PatternCreate, db: Session = Depends(get_db)):
    if db.get(models.Pattern, payload.id) is not None:
        raise HTTPException(status_code=409, detail=f"Pattern '{payload.id}' already exists")

    pattern = models.Pattern(
        id=payload.id,
        name=payload.name,
        summary=payload.summary,
        description=payload.description,
        legacy_stack=payload.legacy_stack,
        category=payload.category,
        detection_rules=payload.detection_rules.model_dump(),
        typical_indicators=payload.typical_indicators,
        known_risks=payload.known_risks,
        status=payload.status,
    )
    db.add(pattern)
    db.commit()
    db.refresh(pattern)
    return _pattern_detail(db, pattern)


@router.put("/{pattern_id}", response_model=schemas.PatternDetail)
def update_pattern(pattern_id: str, payload: schemas.PatternUpdate, db: Session = Depends(get_db)):
    pattern = db.get(models.Pattern, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail=f"Pattern '{pattern_id}' not found")

    new_detection_rules = payload.detection_rules.model_dump()
    material_change = (
        new_detection_rules != pattern.detection_rules
        or payload.name != pattern.name
        or payload.legacy_stack != pattern.legacy_stack
        or payload.category != pattern.category
    )

    pattern.name = payload.name
    pattern.summary = payload.summary
    pattern.description = payload.description
    pattern.legacy_stack = payload.legacy_stack
    pattern.category = payload.category
    pattern.detection_rules = new_detection_rules
    pattern.typical_indicators = payload.typical_indicators
    pattern.known_risks = payload.known_risks
    if payload.status is not None:
        pattern.status = payload.status
    if material_change:
        pattern.version += 1
    pattern.updated_at = datetime.datetime.now(datetime.timezone.utc)

    db.commit()
    db.refresh(pattern)
    return _pattern_detail(db, pattern)


@router.delete("/{pattern_id}", response_model=schemas.PatternDeleteResponse)
def delete_pattern(pattern_id: str, db: Session = Depends(get_db)):
    pattern = db.get(models.Pattern, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail=f"Pattern '{pattern_id}' not found")

    pattern.status = "deprecated"
    pattern.updated_at = datetime.datetime.now(datetime.timezone.utc)

    referenced = (
        db.query(func.count(models.DecisionRecord.id))
        .filter(
            models.DecisionRecord.pattern_id == pattern_id,
            models.DecisionRecord.status != "superseded",
        )
        .scalar()
    )

    db.commit()
    return schemas.PatternDeleteResponse(
        id=pattern.id, status=pattern.status, referenced_by_decisions=referenced
    )
