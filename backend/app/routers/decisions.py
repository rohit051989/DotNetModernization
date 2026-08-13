import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_db
from app.schemas import CONSUMER_IMPACT_RANK

router = APIRouter(prefix="/api", tags=["decisions"])


def _decision_response(db: Session, decision: models.DecisionRecord) -> schemas.DecisionRecord:
    pattern = db.get(models.Pattern, decision.pattern_id)
    target_state = (
        db.get(models.TargetStateOption, decision.selected_target_state_id)
        if decision.selected_target_state_id
        else None
    )
    return schemas.DecisionRecord(
        id=str(decision.id),
        engagement_id=decision.engagement_id,
        pattern_id=decision.pattern_id,
        pattern_name=pattern.name if pattern else decision.pattern_id,
        selected_target_state_id=decision.selected_target_state_id,
        selected_target_state_name=target_state.name if target_state else None,
        candidates_considered=decision.candidates_considered,
        evaluation_notes=decision.evaluation_notes,
        forcing_factor=decision.forcing_factor,
        rationale=decision.rationale,
        approver_name=decision.approver_name,
        approver_role=decision.approver_role,
        decision_date=decision.decision_date,
        status=decision.status,
        created_at=decision.created_at,
        updated_at=decision.updated_at,
        deleted_at=decision.deleted_at,
        deleted_by=decision.deleted_by,
    )


def _validate_decision(
    db: Session,
    pattern_id: str,
    selected_target_state_id: str | None,
    candidates_considered: list[str] | None,
    forcing_factor: str | None,
    rationale: str | None,
    approver_name: str | None,
    decision_date: datetime.date | None,
    status: str,
) -> None:
    """Enforces the decision-record validation rules from 02-DATA-MODEL.md."""
    errors: list[dict] = []

    selected_option = None
    if selected_target_state_id:
        selected_option = db.get(models.TargetStateOption, selected_target_state_id)
        if selected_option is None:
            errors.append(
                {
                    "field": "selected_target_state_id",
                    "message": f"Target state option '{selected_target_state_id}' does not exist.",
                }
            )
        elif selected_option.pattern_id != pattern_id:
            errors.append(
                {
                    "field": "selected_target_state_id",
                    "message": (
                        f"Target state option '{selected_target_state_id}' belongs to pattern "
                        f"'{selected_option.pattern_id}', not '{pattern_id}'."
                    ),
                }
            )

    if status == "approved":
        if not selected_target_state_id:
            errors.append(
                {
                    "field": "selected_target_state_id",
                    "message": "An approved decision requires a selected target state option.",
                }
            )
        if not rationale:
            errors.append(
                {"field": "rationale", "message": "An approved decision requires a rationale."}
            )
        if not approver_name:
            errors.append(
                {
                    "field": "approver_name",
                    "message": "An approved decision requires an approver name.",
                }
            )
        if not decision_date:
            errors.append(
                {
                    "field": "decision_date",
                    "message": "An approved decision requires a decision date.",
                }
            )

        if selected_option is not None and candidates_considered:
            candidate_options = (
                db.query(models.TargetStateOption)
                .filter(models.TargetStateOption.id.in_(candidates_considered))
                .all()
            )
            if candidate_options:
                lowest = min(
                    candidate_options, key=lambda o: CONSUMER_IMPACT_RANK[o.consumer_impact]
                )
                selected_rank = CONSUMER_IMPACT_RANK[selected_option.consumer_impact]
                lowest_rank = CONSUMER_IMPACT_RANK[lowest.consumer_impact]
                if selected_rank > lowest_rank and not forcing_factor:
                    errors.append(
                        {
                            "field": "forcing_factor",
                            "message": (
                                f"{selected_option.name} has higher consumer impact "
                                f"({selected_option.consumer_impact}) than the lowest candidate "
                                f"{lowest.name} ({lowest.consumer_impact}). A forcing factor is "
                                "required to justify the deviation."
                            ),
                        }
                    )

    if errors:
        raise HTTPException(status_code=422, detail=errors)


@router.get(
    "/engagements/{engagement_id}/decisions", response_model=list[schemas.DecisionRecord]
)
def list_decisions(
    engagement_id: str, include_deleted: bool = Query(False), db: Session = Depends(get_db)
):
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None:
        raise HTTPException(status_code=404, detail=f"Engagement '{engagement_id}' not found")

    query = db.query(models.DecisionRecord).filter(
        models.DecisionRecord.engagement_id == engagement_id
    )
    if not include_deleted:
        query = query.filter(models.DecisionRecord.deleted_at.is_(None))
    decisions = query.order_by(models.DecisionRecord.created_at).all()
    return [_decision_response(db, d) for d in decisions]


@router.post(
    "/engagements/{engagement_id}/decisions",
    response_model=schemas.DecisionRecord,
    status_code=201,
)
def create_decision(
    engagement_id: str, payload: schemas.DecisionRecordCreate, db: Session = Depends(get_db)
):
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None:
        raise HTTPException(status_code=404, detail=f"Engagement '{engagement_id}' not found")

    pattern = db.get(models.Pattern, payload.pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail=f"Pattern '{payload.pattern_id}' not found")

    _validate_decision(
        db,
        pattern_id=payload.pattern_id,
        selected_target_state_id=payload.selected_target_state_id,
        candidates_considered=payload.candidates_considered,
        forcing_factor=payload.forcing_factor,
        rationale=payload.rationale,
        approver_name=payload.approver_name,
        decision_date=payload.decision_date,
        status=payload.status,
    )

    live_conflict = (
        db.query(models.DecisionRecord)
        .filter(
            models.DecisionRecord.engagement_id == engagement_id,
            models.DecisionRecord.pattern_id == payload.pattern_id,
            models.DecisionRecord.status != "superseded",
        )
        .first()
    )
    if live_conflict is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Engagement '{engagement_id}' already has a live decision record "
                f"'{live_conflict.id}' for pattern '{payload.pattern_id}'; supersede it first."
            ),
        )

    decision = models.DecisionRecord(
        id=uuid.uuid4(),
        engagement_id=engagement_id,
        pattern_id=payload.pattern_id,
        selected_target_state_id=payload.selected_target_state_id,
        candidates_considered=payload.candidates_considered,
        evaluation_notes=payload.evaluation_notes,
        forcing_factor=payload.forcing_factor,
        rationale=payload.rationale,
        approver_name=payload.approver_name,
        approver_role=payload.approver_role,
        decision_date=payload.decision_date,
        status=payload.status,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return _decision_response(db, decision)


@router.get("/decisions/{decision_id}", response_model=schemas.DecisionRecord)
def get_decision(
    decision_id: uuid.UUID, include_deleted: bool = Query(False), db: Session = Depends(get_db)
):
    decision = db.get(models.DecisionRecord, decision_id)
    if decision is None or (decision.deleted_at is not None and not include_deleted):
        raise HTTPException(status_code=404, detail=f"Decision record '{decision_id}' not found")
    return _decision_response(db, decision)


@router.put("/decisions/{decision_id}", response_model=schemas.DecisionRecord)
def update_decision(
    decision_id: uuid.UUID, payload: schemas.DecisionRecordUpdate, db: Session = Depends(get_db)
):
    decision = db.get(models.DecisionRecord, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail=f"Decision record '{decision_id}' not found")

    new_status = payload.status if payload.status is not None else decision.status
    new_selected = (
        payload.selected_target_state_id
        if payload.selected_target_state_id is not None
        else decision.selected_target_state_id
    )
    new_candidates = (
        payload.candidates_considered
        if payload.candidates_considered is not None
        else decision.candidates_considered
    )
    new_forcing_factor = (
        payload.forcing_factor if payload.forcing_factor is not None else decision.forcing_factor
    )
    new_rationale = payload.rationale if payload.rationale is not None else decision.rationale
    new_approver_name = (
        payload.approver_name if payload.approver_name is not None else decision.approver_name
    )
    new_decision_date = (
        payload.decision_date if payload.decision_date is not None else decision.decision_date
    )

    _validate_decision(
        db,
        pattern_id=decision.pattern_id,
        selected_target_state_id=new_selected,
        candidates_considered=new_candidates,
        forcing_factor=new_forcing_factor,
        rationale=new_rationale,
        approver_name=new_approver_name,
        decision_date=new_decision_date,
        status=new_status,
    )

    decision.selected_target_state_id = new_selected
    decision.candidates_considered = new_candidates
    decision.evaluation_notes = (
        payload.evaluation_notes
        if payload.evaluation_notes is not None
        else decision.evaluation_notes
    )
    decision.forcing_factor = new_forcing_factor
    decision.rationale = new_rationale
    decision.approver_name = new_approver_name
    decision.approver_role = (
        payload.approver_role if payload.approver_role is not None else decision.approver_role
    )
    decision.decision_date = new_decision_date
    decision.status = new_status
    decision.updated_at = datetime.datetime.now(datetime.timezone.utc)

    db.commit()
    db.refresh(decision)
    return _decision_response(db, decision)


@router.post("/decisions/{decision_id}/supersede", response_model=schemas.DecisionRecord)
def supersede_decision(decision_id: uuid.UUID, db: Session = Depends(get_db)):
    decision = db.get(models.DecisionRecord, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail=f"Decision record '{decision_id}' not found")

    decision.status = "superseded"
    decision.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(decision)
    return _decision_response(db, decision)
