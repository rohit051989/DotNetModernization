import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_db
from app.errors import ErrorResponse, error

router = APIRouter(prefix="/api", tags=["Target States"])

_NOT_FOUND = {"model": ErrorResponse, "description": "No target state option exists with this id."}

_IMPACT_ORDER = case(
    (models.TargetStateOption.consumer_impact == "none", 0),
    (models.TargetStateOption.consumer_impact == "low", 1),
    (models.TargetStateOption.consumer_impact == "medium", 2),
    (models.TargetStateOption.consumer_impact == "high", 3),
)
_EFFORT_ORDER = case(
    (models.TargetStateOption.effort == "low", 0),
    (models.TargetStateOption.effort == "medium", 1),
    (models.TargetStateOption.effort == "high", 2),
)


def get_target_states_for_pattern(
    db: Session, pattern_id: str, include_deleted: bool = False
) -> list[models.TargetStateOption]:
    """Lowest consumer_impact first, then lowest effort — the presumptive choice always leads."""
    query = db.query(models.TargetStateOption).filter(
        models.TargetStateOption.pattern_id == pattern_id
    )
    if not include_deleted:
        query = query.filter(models.TargetStateOption.deleted_at.is_(None))
    return query.order_by(_IMPACT_ORDER, _EFFORT_ORDER).all()


def _get_visible_pattern(db: Session, pattern_id: str, include_deleted: bool) -> models.Pattern:
    pattern = db.get(models.Pattern, pattern_id)
    if pattern is None or (pattern.deleted_at is not None and not include_deleted):
        raise error(404, f"Pattern '{pattern_id}' not found", code="NOT_FOUND")
    return pattern


def _clear_other_recommendations(db: Session, pattern_id: str, keep_id: str) -> None:
    """At most one is_recommended=true per pattern, enforced here rather than a
    DB constraint (03-BACKEND-SPEC.md)."""
    (
        db.query(models.TargetStateOption)
        .filter(
            models.TargetStateOption.pattern_id == pattern_id,
            models.TargetStateOption.id != keep_id,
            models.TargetStateOption.is_recommended.is_(True),
        )
        .update({"is_recommended": False}, synchronize_session=False)
    )


@router.get(
    "/patterns/{pattern_id}/target-states",
    response_model=list[schemas.TargetStateDetail],
    summary="List target state options for a pattern",
    response_description="Options for this pattern, lowest consumer_impact first, then lowest effort.",
    operation_id="list_target_states",
    responses={404: {"model": ErrorResponse, "description": "No pattern exists with this id."}},
)
def list_target_states(
    pattern_id: str,
    include_deleted: bool = Query(False, description="Include soft-deleted options."),
    db: Session = Depends(get_db),
):
    _get_visible_pattern(db, pattern_id, include_deleted)
    return get_target_states_for_pattern(db, pattern_id, include_deleted=include_deleted)


@router.post(
    "/patterns/{pattern_id}/target-states",
    response_model=schemas.TargetStateDetail,
    status_code=201,
    summary="Create a target state option under a pattern",
    response_description="The newly created option.",
    operation_id="create_target_state",
    responses={
        404: {"model": ErrorResponse, "description": "No pattern exists with this id."},
        409: {"model": ErrorResponse, "description": "This id already exists, or the (pattern_id, name) pair is already used."},
    },
)
def create_target_state(
    pattern_id: str, payload: schemas.TargetStateCreate, db: Session = Depends(get_db)
):
    """
    `id` must be a lowercase, hyphenated slug. Setting `is_recommended: true`
    clears the flag on every other option under this pattern in the same
    request — at most one recommended option per pattern.
    """
    _get_visible_pattern(db, pattern_id, include_deleted=False)

    if db.get(models.TargetStateOption, payload.id) is not None:
        raise error(409, f"Target state option '{payload.id}' already exists", field="id", code="DUPLICATE_ID")

    duplicate_name = (
        db.query(models.TargetStateOption)
        .filter(
            models.TargetStateOption.pattern_id == pattern_id,
            models.TargetStateOption.name == payload.name,
        )
        .first()
    )
    if duplicate_name is not None:
        raise error(
            409,
            f"Target state option named '{payload.name}' already exists for pattern '{pattern_id}'",
            field="name",
            code="DUPLICATE_NAME",
        )

    option = models.TargetStateOption(
        id=payload.id,
        pattern_id=pattern_id,
        name=payload.name,
        summary=payload.summary,
        target_stack=payload.target_stack,
        consumer_impact=payload.consumer_impact,
        effort=payload.effort,
        linux_compatible=payload.linux_compatible,
        container_ready=payload.container_ready,
        is_lift_and_shift=payload.is_lift_and_shift,
        is_recommended=payload.is_recommended,
        engine_support=payload.engine_support.model_dump() if payload.engine_support else None,
        playbook_md=payload.playbook_md,
        prerequisites=payload.prerequisites,
        known_limitations=payload.known_limitations,
        status=payload.status,
    )
    db.add(option)
    if payload.is_recommended:
        db.flush()  # option must exist before excluding its id from the clear
        _clear_other_recommendations(db, pattern_id, option.id)
    db.commit()
    db.refresh(option)
    return option


@router.get(
    "/target-states/{target_state_id}",
    response_model=schemas.TargetStateDetail,
    summary="Get a target state option",
    response_description="The target state option.",
    operation_id="get_target_state",
    responses={404: _NOT_FOUND},
)
def get_target_state(
    target_state_id: str,
    include_deleted: bool = Query(False, description="Return the option even if it is soft-deleted."),
    db: Session = Depends(get_db),
):
    option = db.get(models.TargetStateOption, target_state_id)
    if option is None or (option.deleted_at is not None and not include_deleted):
        raise error(404, f"Target state option '{target_state_id}' not found", code="NOT_FOUND")
    return option


@router.put(
    "/target-states/{target_state_id}",
    response_model=schemas.TargetStateDetail,
    summary="Update a target state option",
    response_description="The updated option.",
    operation_id="update_target_state",
    responses={
        404: _NOT_FOUND,
        409: {"model": ErrorResponse, "description": "Another option under the same pattern already has this name."},
    },
)
def update_target_state(
    target_state_id: str, payload: schemas.TargetStateUpdate, db: Session = Depends(get_db)
):
    """`version` increments only on a material change (`name`, `target_stack`,
    `consumer_impact`, or `effort`)."""
    option = db.get(models.TargetStateOption, target_state_id)
    if option is None:
        raise error(404, f"Target state option '{target_state_id}' not found", code="NOT_FOUND")

    duplicate_name = (
        db.query(models.TargetStateOption)
        .filter(
            models.TargetStateOption.pattern_id == option.pattern_id,
            models.TargetStateOption.name == payload.name,
            models.TargetStateOption.id != target_state_id,
        )
        .first()
    )
    if duplicate_name is not None:
        raise error(
            409,
            f"Target state option named '{payload.name}' already exists for pattern '{option.pattern_id}'",
            field="name",
            code="DUPLICATE_NAME",
        )

    material_change = (
        payload.name != option.name
        or payload.target_stack != option.target_stack
        or payload.consumer_impact != option.consumer_impact
        or payload.effort != option.effort
    )

    option.name = payload.name
    option.summary = payload.summary
    option.target_stack = payload.target_stack
    option.consumer_impact = payload.consumer_impact
    option.effort = payload.effort
    option.linux_compatible = payload.linux_compatible
    option.container_ready = payload.container_ready
    option.is_lift_and_shift = payload.is_lift_and_shift
    option.is_recommended = payload.is_recommended
    option.engine_support = payload.engine_support.model_dump() if payload.engine_support else None
    option.playbook_md = payload.playbook_md
    option.prerequisites = payload.prerequisites
    option.known_limitations = payload.known_limitations
    if payload.status is not None:
        option.status = payload.status
    if material_change:
        option.version += 1
    option.updated_at = datetime.datetime.now(datetime.timezone.utc)

    if payload.is_recommended:
        _clear_other_recommendations(db, option.pattern_id, option.id)

    db.commit()
    db.refresh(option)
    return option


@router.post(
    "/target-states/{target_state_id}/deprecate",
    response_model=schemas.TargetStateDeprecateResponse,
    summary="Deprecate a target state option",
    response_description="The option's new status.",
    operation_id="deprecate_target_state",
    responses={
        404: _NOT_FOUND,
        409: {"model": ErrorResponse, "description": "A non-superseded, non-deleted decision record has this option approved as its selection."},
    },
)
def deprecate_target_state(target_state_id: str, db: Session = Depends(get_db)):
    """
    Sets `status = 'deprecated'`. Distinct from `DELETE` (soft delete): the
    option remains visible in every list/get response. Refused with 409 only
    if a non-superseded **approved** decision selects this option — a
    narrower guard than `DELETE`'s, since deprecation is a softer signal.
    """
    option = db.get(models.TargetStateOption, target_state_id)
    if option is None:
        raise error(404, f"Target state option '{target_state_id}' not found", code="NOT_FOUND")

    approved_reference = (
        db.query(models.DecisionRecord)
        .filter(
            models.DecisionRecord.selected_target_state_id == target_state_id,
            models.DecisionRecord.status == "approved",
            models.DecisionRecord.deleted_at.is_(None),
        )
        .first()
    )
    if approved_reference is not None:
        raise error(
            409,
            f"Target state option '{target_state_id}' is the approved selection for "
            f"decision record '{approved_reference.id}' in engagement "
            f"'{approved_reference.engagement_id}'; supersede that decision first.",
            code="APPROVED_ELSEWHERE",
        )

    option.status = "deprecated"
    option.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    return schemas.TargetStateDeprecateResponse(id=option.id, status=option.status)


@router.delete(
    "/target-states/{target_state_id}",
    response_model=schemas.TargetStateSoftDeleteResponse,
    summary="Soft-delete a target state option",
    response_description="When the soft delete took effect.",
    operation_id="delete_target_state",
    responses={
        404: _NOT_FOUND,
        409: {"model": ErrorResponse, "description": "A non-superseded decision record (any status) has this option selected."},
    },
)
def delete_target_state(
    target_state_id: str,
    deleted_by: str | None = Query(None, description="Free-text identity performing the delete."),
    db: Session = Depends(get_db),
):
    """
    Guarded more broadly than deprecate: refused if **any** non-superseded
    decision record (parked, in_review, or approved) has this option
    selected and is not itself deleted — removal is a stronger action than
    deprecation, so the check is correspondingly wider.
    """
    option = db.get(models.TargetStateOption, target_state_id)
    if option is None or option.deleted_at is not None:
        raise error(404, f"Target state option '{target_state_id}' not found", code="NOT_FOUND")

    live_reference = (
        db.query(models.DecisionRecord)
        .filter(
            models.DecisionRecord.selected_target_state_id == target_state_id,
            models.DecisionRecord.status != "superseded",
            models.DecisionRecord.deleted_at.is_(None),
        )
        .first()
    )
    if live_reference is not None:
        raise error(
            409,
            f"Target state option '{target_state_id}' is referenced by non-superseded "
            f"decision record '{live_reference.id}' in engagement "
            f"'{live_reference.engagement_id}'; supersede that decision first.",
            code="REFERENCED_BY_DECISION",
        )

    option.deleted_at = datetime.datetime.now(datetime.timezone.utc)
    option.deleted_by = deleted_by
    db.commit()
    return schemas.TargetStateSoftDeleteResponse(id=option.id, deleted_at=option.deleted_at)


@router.post(
    "/target-states/{target_state_id}/restore",
    response_model=schemas.TargetStateSoftDeleteResponse,
    summary="Restore a soft-deleted target state option",
    response_description="deleted_at is now null.",
    operation_id="restore_target_state",
    responses={404: _NOT_FOUND},
)
def restore_target_state(target_state_id: str, db: Session = Depends(get_db)):
    """Clears `deleted_at`/`deleted_by` unconditionally; `status` is untouched.
    Admin-only in intent; unguarded for now — no auth system exists yet (see CLAUDE.md)."""
    # TODO: gate behind an admin role once auth exists.
    option = db.get(models.TargetStateOption, target_state_id)
    if option is None:
        raise error(404, f"Target state option '{target_state_id}' not found", code="NOT_FOUND")

    option.deleted_at = None
    option.deleted_by = None
    db.commit()
    return schemas.TargetStateSoftDeleteResponse(id=option.id, deleted_at=None)
