import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_db

router = APIRouter(prefix="/api", tags=["target-states"])

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
    db: Session, pattern_id: str
) -> list[models.TargetStateOption]:
    """Lowest consumer_impact first, then lowest effort — the presumptive choice always leads."""
    return (
        db.query(models.TargetStateOption)
        .filter(models.TargetStateOption.pattern_id == pattern_id)
        .order_by(_IMPACT_ORDER, _EFFORT_ORDER)
        .all()
    )


@router.get(
    "/patterns/{pattern_id}/target-states",
    response_model=list[schemas.TargetStateDetail],
)
def list_target_states(pattern_id: str, db: Session = Depends(get_db)):
    pattern = db.get(models.Pattern, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail=f"Pattern '{pattern_id}' not found")
    return get_target_states_for_pattern(db, pattern_id)


@router.post(
    "/patterns/{pattern_id}/target-states",
    response_model=schemas.TargetStateDetail,
    status_code=201,
)
def create_target_state(
    pattern_id: str, payload: schemas.TargetStateCreate, db: Session = Depends(get_db)
):
    pattern = db.get(models.Pattern, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail=f"Pattern '{pattern_id}' not found")

    if db.get(models.TargetStateOption, payload.id) is not None:
        raise HTTPException(
            status_code=409, detail=f"Target state option '{payload.id}' already exists"
        )

    duplicate_name = (
        db.query(models.TargetStateOption)
        .filter(
            models.TargetStateOption.pattern_id == pattern_id,
            models.TargetStateOption.name == payload.name,
        )
        .first()
    )
    if duplicate_name is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Target state option named '{payload.name}' already exists "
                f"for pattern '{pattern_id}'"
            ),
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
        engine_support=payload.engine_support.model_dump() if payload.engine_support else None,
        playbook_md=payload.playbook_md,
        prerequisites=payload.prerequisites,
        known_limitations=payload.known_limitations,
        status=payload.status,
    )
    db.add(option)
    db.commit()
    db.refresh(option)
    return option


@router.get("/target-states/{target_state_id}", response_model=schemas.TargetStateDetail)
def get_target_state(target_state_id: str, db: Session = Depends(get_db)):
    option = db.get(models.TargetStateOption, target_state_id)
    if option is None:
        raise HTTPException(
            status_code=404, detail=f"Target state option '{target_state_id}' not found"
        )
    return option


@router.put("/target-states/{target_state_id}", response_model=schemas.TargetStateDetail)
def update_target_state(
    target_state_id: str, payload: schemas.TargetStateUpdate, db: Session = Depends(get_db)
):
    option = db.get(models.TargetStateOption, target_state_id)
    if option is None:
        raise HTTPException(
            status_code=404, detail=f"Target state option '{target_state_id}' not found"
        )

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
        raise HTTPException(
            status_code=409,
            detail=(
                f"Target state option named '{payload.name}' already exists "
                f"for pattern '{option.pattern_id}'"
            ),
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
    option.engine_support = payload.engine_support.model_dump() if payload.engine_support else None
    option.playbook_md = payload.playbook_md
    option.prerequisites = payload.prerequisites
    option.known_limitations = payload.known_limitations
    if payload.status is not None:
        option.status = payload.status
    if material_change:
        option.version += 1
    option.updated_at = datetime.datetime.now(datetime.timezone.utc)

    db.commit()
    db.refresh(option)
    return option


@router.delete("/target-states/{target_state_id}", response_model=schemas.TargetStateDeleteResponse)
def delete_target_state(target_state_id: str, db: Session = Depends(get_db)):
    option = db.get(models.TargetStateOption, target_state_id)
    if option is None:
        raise HTTPException(
            status_code=404, detail=f"Target state option '{target_state_id}' not found"
        )

    approved_reference = (
        db.query(models.DecisionRecord)
        .filter(
            models.DecisionRecord.selected_target_state_id == target_state_id,
            models.DecisionRecord.status == "approved",
        )
        .first()
    )
    if approved_reference is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Target state option '{target_state_id}' is the approved selection for "
                f"decision record '{approved_reference.id}' in engagement "
                f"'{approved_reference.engagement_id}'; supersede that decision first."
            ),
        )

    option.status = "deprecated"
    option.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    return schemas.TargetStateDeleteResponse(id=option.id, status=option.status)
