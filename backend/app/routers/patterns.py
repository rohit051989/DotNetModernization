import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import catalog_rules, models, schemas
from app.db import get_db
from app.errors import ErrorResponse, error
from app.routers.target_states import get_target_states_for_pattern

router = APIRouter(prefix="/api/patterns", tags=["Patterns"])

_NOT_FOUND = {"model": ErrorResponse, "description": "No pattern exists with this id (or it is soft-deleted and `include_deleted` was not set)."}

_DEFAULT_THRESHOLDS = {"minimumScore": 70, "highConfidenceScore": 90}


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
        classification_role=pattern.classification_role,
        classification_family=pattern.classification_family,
        classification_value=pattern.classification_value,
        scope=pattern.scope,
        priority=pattern.priority,
        compatible_with=pattern.compatible_with,
        conflicts_with=pattern.conflicts_with,
        anchor_signals=pattern.anchor_signals,
        eligibility=pattern.eligibility,
        analysis_requirements=pattern.analysis_requirements,
        thresholds=pattern.thresholds,
        rules_status=pattern.rules_status,
        required_signals_pending=pattern.required_signals_pending,
        created_at=pattern.created_at,
        updated_at=pattern.updated_at,
        deleted_at=pattern.deleted_at,
        deleted_by=pattern.deleted_by,
        target_state_options=[
            schemas.TargetStateSummary.model_validate(option) for option in options
        ],
    )


def _resolve_classification_fields(
    payload: schemas.PatternBase, existing: models.Pattern | None
) -> dict:
    """Merges the optional Part B1 fields onto an existing pattern (update:
    omitted means unchanged) or applies J1-migration-equivalent defaults
    (create: omitted means default). Returns plain values ready to assign to
    the model and to run B3 validation against."""

    def pick(payload_value, existing_value, default):
        if payload_value is not None:
            return payload_value
        if existing is not None:
            return existing_value
        return default

    detection_rules = (
        payload.detection_rules.model_dump(by_alias=True)
        if payload.detection_rules is not None
        else (existing.detection_rules if existing is not None else schemas.SignalRuleSet.empty().model_dump(by_alias=True))
    )
    return {
        "detection_rules": detection_rules,
        "classification_role": pick(payload.classification_role, existing.classification_role if existing else None, "PRIMARY"),
        "classification_family": pick(payload.classification_family, existing.classification_family if existing else None, None),
        "classification_value": pick(payload.classification_value, existing.classification_value if existing else None, None),
        "scope": pick(payload.scope, existing.scope if existing else None, "PROJECT"),
        "priority": pick(payload.priority, existing.priority if existing else None, 50),
        "compatible_with": pick(payload.compatible_with, existing.compatible_with if existing else None, []),
        "conflicts_with": pick(payload.conflicts_with, existing.conflicts_with if existing else None, []),
        "anchor_signals": pick(payload.anchor_signals, existing.anchor_signals if existing else None, []),
        "eligibility": (
            payload.eligibility.model_dump() if payload.eligibility is not None
            else (existing.eligibility if existing is not None else None)
        ),
        "analysis_requirements": (
            payload.analysis_requirements.model_dump() if payload.analysis_requirements is not None
            else (existing.analysis_requirements if existing is not None else None)
        ),
        "thresholds": (
            payload.thresholds.model_dump() if payload.thresholds is not None
            else (existing.thresholds if existing is not None else dict(_DEFAULT_THRESHOLDS))
        ),
        "rules_status": pick(payload.rules_status, existing.rules_status if existing else None, "draft"),
        "required_signals_pending": (
            [entry.model_dump() for entry in payload.required_signals_pending]
            if payload.required_signals_pending is not None
            else (existing.required_signals_pending if existing is not None else [])
        ),
    }


def _apply_classification_fields(pattern: models.Pattern, db: Session, resolved: dict) -> None:
    """Validates (Part B3, compatibility) and assigns the resolved
    classification fields onto `pattern`. Rule ids are backfilled positionally
    before validation so id uniqueness checks see the final shape."""
    detection_rules = catalog_rules.assign_positional_rule_ids(resolved["detection_rules"])
    catalog_rules.validate_rule_ids_unique(detection_rules)
    catalog_rules.validate_signal_references(
        detection_rules,
        resolved["anchor_signals"],
        resolved["rules_status"],
        resolved["required_signals_pending"],
    )
    catalog_rules.validate_compatibility(db, resolved["compatible_with"], resolved["conflicts_with"])

    pattern.detection_rules = detection_rules
    pattern.classification_role = resolved["classification_role"]
    pattern.classification_family = resolved["classification_family"]
    pattern.classification_value = resolved["classification_value"]
    pattern.scope = resolved["scope"]
    pattern.priority = resolved["priority"]
    pattern.compatible_with = resolved["compatible_with"]
    pattern.conflicts_with = resolved["conflicts_with"]
    pattern.anchor_signals = resolved["anchor_signals"]
    pattern.eligibility = resolved["eligibility"]
    pattern.analysis_requirements = resolved["analysis_requirements"]
    pattern.thresholds = resolved["thresholds"]
    pattern.rules_status = resolved["rules_status"]
    pattern.required_signals_pending = resolved["required_signals_pending"]


@router.get(
    "",
    response_model=list[schemas.PatternSummary],
    summary="List master catalog patterns",
    response_description="Patterns matching the filters, ordered by id.",
    operation_id="list_patterns",
)
def list_patterns(
    status: str | None = Query(None, description="Filter by lifecycle status: 'draft', 'active', or 'deprecated'."),
    category: str | None = Query(None, description="Filter by exact category match."),
    q: str | None = Query(None, description="Case-insensitive substring match against name, summary, and legacy_stack."),
    include_deleted: bool = Query(False, description="Include soft-deleted patterns."),
    db: Session = Depends(get_db),
):
    query = db.query(models.Pattern)
    if not include_deleted:
        query = query.filter(models.Pattern.deleted_at.is_(None))
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
        .filter(
            models.TargetStateOption.status != "deprecated",
            models.TargetStateOption.deleted_at.is_(None),
        )
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
            deleted_at=p.deleted_at,
            deleted_by=p.deleted_by,
        )
        for p in patterns
    ]


@router.get(
    "/{pattern_id}",
    response_model=schemas.PatternDetail,
    summary="Get a pattern, with its target state options",
    response_description="The pattern, including every non-deleted target state option nested under it.",
    operation_id="get_pattern",
    responses={404: _NOT_FOUND},
)
def get_pattern(
    pattern_id: str,
    include_deleted: bool = Query(False, description="Return the pattern even if it is soft-deleted."),
    db: Session = Depends(get_db),
):
    pattern = db.get(models.Pattern, pattern_id)
    if pattern is None or (pattern.deleted_at is not None and not include_deleted):
        raise error(404, f"Pattern '{pattern_id}' not found", code="NOT_FOUND")
    return _pattern_detail(db, pattern)


@router.post(
    "",
    response_model=schemas.PatternDetail,
    status_code=201,
    summary="Create a master catalog pattern",
    response_description="The newly created pattern.",
    operation_id="create_pattern",
    responses={409: {"model": ErrorResponse, "description": "A pattern with this id already exists, including a soft-deleted one — restore it instead of recreating it."}},
)
def create_pattern(payload: schemas.PatternCreate, db: Session = Depends(get_db)):
    """`id` must be a lowercase, hyphenated slug (`^[a-z0-9]+(-[a-z0-9]+)*$`)."""
    if db.get(models.Pattern, payload.id) is not None:
        raise error(409, f"Pattern '{payload.id}' already exists", field="id", code="DUPLICATE_ID")

    resolved = _resolve_classification_fields(payload, existing=None)

    pattern = models.Pattern(
        id=payload.id,
        name=payload.name,
        summary=payload.summary,
        description=payload.description,
        legacy_stack=payload.legacy_stack,
        category=payload.category,
        typical_indicators=payload.typical_indicators,
        known_risks=payload.known_risks,
        status=payload.status,
    )
    _apply_classification_fields(pattern, db, resolved)
    db.add(pattern)
    catalog_rules.bump_catalog_revision(db, "pattern", pattern.id, "insert")
    db.commit()
    db.refresh(pattern)
    return _pattern_detail(db, pattern)


@router.put(
    "/{pattern_id}",
    response_model=schemas.PatternDetail,
    summary="Update a pattern",
    response_description="The updated pattern.",
    operation_id="update_pattern",
    responses={404: _NOT_FOUND},
)
def update_pattern(pattern_id: str, payload: schemas.PatternUpdate, db: Session = Depends(get_db)):
    """`version` increments only when a detection rule, `name`,
    `legacy_stack` or `category` changes — cosmetic edits to `description`
    do not bump it. The Part B1 classification fields (`detection_rules`,
    `classification_role`, `scope`, etc.) are left untouched when omitted
    from the payload."""
    pattern = db.get(models.Pattern, pattern_id)
    if pattern is None:
        raise error(404, f"Pattern '{pattern_id}' not found", code="NOT_FOUND")

    resolved = _resolve_classification_fields(payload, existing=pattern)
    material_change = (
        resolved["detection_rules"] != pattern.detection_rules
        or payload.name != pattern.name
        or payload.legacy_stack != pattern.legacy_stack
        or payload.category != pattern.category
    )

    pattern.name = payload.name
    pattern.summary = payload.summary
    pattern.description = payload.description
    pattern.legacy_stack = payload.legacy_stack
    pattern.category = payload.category
    pattern.typical_indicators = payload.typical_indicators
    pattern.known_risks = payload.known_risks
    if payload.status is not None:
        pattern.status = payload.status
    _apply_classification_fields(pattern, db, resolved)
    if material_change:
        pattern.version += 1
    pattern.updated_at = datetime.datetime.now(datetime.timezone.utc)

    catalog_rules.bump_catalog_revision(db, "pattern", pattern.id, "update")
    db.commit()
    db.refresh(pattern)
    return _pattern_detail(db, pattern)


def _count_live_decisions(db: Session, pattern_id: str) -> int:
    """Non-superseded, non-deleted decision records against this pattern, across
    every engagement — the master guard's blast radius is the whole catalog."""
    return (
        db.query(func.count(models.DecisionRecord.id))
        .filter(
            models.DecisionRecord.pattern_id == pattern_id,
            models.DecisionRecord.status != "superseded",
            models.DecisionRecord.deleted_at.is_(None),
        )
        .scalar()
    )


@router.post(
    "/{pattern_id}/deprecate",
    response_model=schemas.PatternDeprecateResponse,
    summary="Deprecate a pattern",
    response_description="The pattern's new status and how many live decisions still reference it.",
    operation_id="deprecate_pattern",
    responses={404: _NOT_FOUND},
)
def deprecate_pattern(pattern_id: str, db: Session = Depends(get_db)):
    """
    Sets `status = 'deprecated'`. **Permissive** — always succeeds, even if
    decision records still reference the pattern; `referenced_by_decisions`
    in the response lets the UI warn without blocking the action.

    Distinct from `DELETE` (soft delete): a deprecated pattern stays fully
    visible in every list/get response and via the status filter. Cascades:
    every non-deleted target state option under this pattern is deprecated
    in the same request.
    """
    pattern = db.get(models.Pattern, pattern_id)
    if pattern is None:
        raise error(404, f"Pattern '{pattern_id}' not found", code="NOT_FOUND")

    pattern.status = "deprecated"
    pattern.updated_at = datetime.datetime.now(datetime.timezone.utc)

    referenced = _count_live_decisions(db, pattern_id)

    # Cascades: a deprecated pattern's target state options are deprecated with it.
    # There is no independent path to keep an option live under a retired pattern.
    (
        db.query(models.TargetStateOption)
        .filter(
            models.TargetStateOption.pattern_id == pattern_id,
            models.TargetStateOption.deleted_at.is_(None),
            models.TargetStateOption.status != "deprecated",
        )
        .update({"status": "deprecated", "updated_at": pattern.updated_at}, synchronize_session=False)
    )

    catalog_rules.bump_catalog_revision(db, "pattern", pattern.id, "update")
    db.commit()
    return schemas.PatternDeprecateResponse(
        id=pattern.id, status=pattern.status, referenced_by_decisions=referenced
    )


@router.delete(
    "/{pattern_id}",
    response_model=schemas.PatternSoftDeleteResponse,
    summary="Soft-delete a pattern",
    response_description="When the soft delete took effect.",
    operation_id="delete_pattern",
    responses={
        404: _NOT_FOUND,
        409: {"model": ErrorResponse, "description": "A non-superseded, non-deleted decision record (in any engagement) still references this pattern."},
    },
)
def delete_pattern(
    pattern_id: str,
    deleted_by: str | None = Query(None, description="Free-text identity performing the delete — there is no auth system yet to source one from."),
    db: Session = Depends(get_db),
):
    """
    Sets `deleted_at`/`deleted_by`, excluding the pattern from every normal
    list/get response and from the export. **Guarded, not permissive** —
    refused with 409 if any non-superseded decision record in any engagement
    still references it; supersede or remove those first. The mere existence
    of target state options never blocks this — it cascades over them
    instead, soft-deleting every non-deleted option under this pattern in
    the same request.

    Distinct from `POST .../deprecate`: that sets a status flag and stays
    visible everywhere; this actually hides the record.
    """
    pattern = db.get(models.Pattern, pattern_id)
    if pattern is None or pattern.deleted_at is not None:
        raise error(404, f"Pattern '{pattern_id}' not found", code="NOT_FOUND")

    # Blocked only by live decisions, in any engagement — never by the mere
    # existence of target state options, which this action cascades over instead.
    live_decisions = _count_live_decisions(db, pattern_id)
    if live_decisions > 0:
        raise error(
            409,
            f"Pattern '{pattern_id}' is referenced by {live_decisions} non-superseded "
            "decision record(s); supersede them first.",
            code="REFERENCED_BY_DECISIONS",
        )

    pattern.deleted_at = datetime.datetime.now(datetime.timezone.utc)
    pattern.deleted_by = deleted_by

    (
        db.query(models.TargetStateOption)
        .filter(
            models.TargetStateOption.pattern_id == pattern_id,
            models.TargetStateOption.deleted_at.is_(None),
        )
        .update(
            {"deleted_at": pattern.deleted_at, "deleted_by": deleted_by},
            synchronize_session=False,
        )
    )

    catalog_rules.bump_catalog_revision(db, "pattern", pattern.id, "soft_delete")
    db.commit()
    return schemas.PatternSoftDeleteResponse(id=pattern.id, deleted_at=pattern.deleted_at)


@router.post(
    "/{pattern_id}/restore",
    response_model=schemas.PatternSoftDeleteResponse,
    summary="Restore a soft-deleted pattern",
    response_description="deleted_at is now null.",
    operation_id="restore_pattern",
    responses={404: {"model": ErrorResponse, "description": "No pattern exists with this id."}},
)
def restore_pattern(pattern_id: str, db: Session = Depends(get_db)):
    """
    Clears `deleted_at`/`deleted_by` unconditionally, deleted or not —
    restoring an already-live pattern is a harmless no-op. `status` is
    untouched, so the pattern reappears exactly as active/deprecated/draft as
    before deletion.

    Admin-only in intent; unguarded for now, like every endpoint in this
    build — no auth system exists yet (see CLAUDE.md).
    """
    # TODO: gate behind an admin role once auth exists.
    pattern = db.get(models.Pattern, pattern_id)
    if pattern is None:
        raise error(404, f"Pattern '{pattern_id}' not found", code="NOT_FOUND")

    pattern.deleted_at = None
    pattern.deleted_by = None
    catalog_rules.bump_catalog_revision(db, "pattern", pattern.id, "update")
    db.commit()
    return schemas.PatternSoftDeleteResponse(id=pattern.id, deleted_at=None)
