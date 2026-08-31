import datetime
import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_db
from app.errors import ErrorResponse, error, errors
from app.schemas import CONSUMER_IMPACT_RANK

router = APIRouter(prefix="/api", tags=["Decisions"])

_DECISION_NOT_FOUND = {"model": ErrorResponse, "description": "No decision record exists with this id."}
_VALIDATION_FAILED = {"model": ErrorResponse, "description": "One or more decision validation rules failed — see 02-DATA-MODEL.md."}


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
        forcing_perspective=decision.forcing_perspective,
        forcing_rationale=decision.forcing_rationale,
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
    forcing_perspective: str | None,
    forcing_rationale: str | None,
    rationale: str | None,
    approver_name: str | None,
    decision_date: datetime.date | None,
    status: str,
) -> None:
    """Enforces the decision-record validation rules from 02-DATA-MODEL.md."""
    problems: list[dict] = []

    selected_option = None
    if selected_target_state_id:
        selected_option = db.get(models.TargetStateOption, selected_target_state_id)
        if selected_option is None:
            problems.append(
                {
                    "field": "selected_target_state_id",
                    "message": f"Target state option '{selected_target_state_id}' does not exist.",
                    "code": "TARGET_STATE_NOT_FOUND",
                }
            )
        elif selected_option.pattern_id != pattern_id:
            problems.append(
                {
                    "field": "selected_target_state_id",
                    "message": (
                        f"Target state option '{selected_target_state_id}' belongs to pattern "
                        f"'{selected_option.pattern_id}', not '{pattern_id}'."
                    ),
                    "code": "TARGET_STATE_WRONG_PATTERN",
                }
            )

    if status == "approved":
        if not selected_target_state_id:
            problems.append(
                {
                    "field": "selected_target_state_id",
                    "message": "An approved decision requires a selected target state option.",
                    "code": "APPROVAL_REQUIRES_SELECTION",
                }
            )
        if not rationale:
            problems.append(
                {
                    "field": "rationale",
                    "message": "An approved decision requires a rationale.",
                    "code": "APPROVAL_REQUIRES_RATIONALE",
                }
            )
        if not approver_name:
            problems.append(
                {
                    "field": "approver_name",
                    "message": "An approved decision requires an approver name.",
                    "code": "APPROVAL_REQUIRES_APPROVER",
                }
            )
        if not decision_date:
            problems.append(
                {
                    "field": "decision_date",
                    "message": "An approved decision requires a decision date.",
                    "code": "APPROVAL_REQUIRES_DATE",
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
                if selected_rank > lowest_rank and not (forcing_perspective and forcing_rationale):
                    missing = [
                        field
                        for field, value in (
                            ("forcing_perspective", forcing_perspective),
                            ("forcing_rationale", forcing_rationale),
                        )
                        if not value
                    ]
                    message = (
                        f"{selected_option.name} has higher consumer impact "
                        f"({selected_option.consumer_impact}) than the lowest candidate "
                        f"{lowest.name} ({lowest.consumer_impact}). Both forcing_perspective and "
                        "forcing_rationale are required to justify the deviation."
                    )
                    problems.extend(
                        {"field": field, "message": message, "code": "FORCING_PERSPECTIVE_AND_RATIONALE_REQUIRED"}
                        for field in missing
                    )

    if problems:
        raise errors(422, problems)


def _apply_decision_fields(decision: models.DecisionRecord, payload) -> None:
    """Partial-update semantics shared by both write paths: a field present
    (non-None) in the payload overwrites; omitted fields leave the existing
    value unchanged."""
    if payload.selected_target_state_id is not None:
        decision.selected_target_state_id = payload.selected_target_state_id
    if payload.candidates_considered is not None:
        decision.candidates_considered = payload.candidates_considered
    if payload.evaluation_notes is not None:
        decision.evaluation_notes = payload.evaluation_notes
    if payload.forcing_perspective is not None:
        decision.forcing_perspective = payload.forcing_perspective
    if payload.forcing_rationale is not None:
        decision.forcing_rationale = payload.forcing_rationale
    if payload.rationale is not None:
        decision.rationale = payload.rationale
    if payload.approver_name is not None:
        decision.approver_name = payload.approver_name
    if payload.approver_role is not None:
        decision.approver_role = payload.approver_role
    if payload.decision_date is not None:
        decision.decision_date = payload.decision_date
    if payload.status is not None:
        decision.status = payload.status
    decision.updated_at = datetime.datetime.now(datetime.timezone.utc)


@router.get(
    "/engagements/{engagement_id}/decisions",
    response_model=list[schemas.DecisionRecord],
    summary="List decision records for an engagement",
    response_description="Decision records ordered by creation time.",
    tags=["Decisions", "Engagements"],
    operation_id="list_engagement_decisions",
    responses={404: {"model": ErrorResponse, "description": "No engagement exists with this id."}},
)
def list_decisions(
    engagement_id: str,
    include_deleted: bool = Query(False, description="Include soft-deleted decision records."),
    db: Session = Depends(get_db),
):

    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")

    query = db.query(models.DecisionRecord).filter(
        models.DecisionRecord.engagement_id == engagement_id
    )
    if not include_deleted:
        query = query.filter(models.DecisionRecord.deleted_at.is_(None))
    decisions = query.order_by(models.DecisionRecord.created_at).all()
    return [_decision_response(db, d) for d in decisions]


@router.get(
    "/engagements/{engagement_id}/patterns/{pattern_id}/decision",
    response_model=schemas.DecisionRecord,
    summary="Get the live decision for a pattern in an engagement",
    response_description="The current (non-superseded, non-deleted) decision record.",
    tags=["Decisions", "Client Catalog"],
    operation_id="get_engagement_pattern_decision",
    responses={404: {"model": ErrorResponse, "description": "No live decision exists for this (engagement, pattern) pair."}},
)
def get_engagement_pattern_decision(
    engagement_id: str, pattern_id: str, db: Session = Depends(get_db)
):
    """
    A decision record is a singleton per `(engagement, pattern)` — this is
    the identity-in-the-path read for it. Returns 404 when no decision has
    been recorded yet; that is the normal "nothing decided" state, not an
    error condition to work around.
    """

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
        raise error(
            404,
            f"No live decision for pattern '{pattern_id}' in engagement '{engagement_id}'",
            code="NOT_FOUND",
        )
    return _decision_response(db, decision)


@router.put(
    "/engagements/{engagement_id}/patterns/{pattern_id}/decision",
    response_model=schemas.DecisionRecord,
    summary="Record or update the decision for a pattern in an engagement",
    response_description="The created or updated decision record.",
    tags=["Decisions", "Client Catalog"],
    operation_id="upsert_engagement_pattern_decision",
    responses={
        404: {"model": ErrorResponse, "description": "No engagement or pattern exists with these ids."},
        422: _VALIDATION_FAILED,
    },
)
def upsert_engagement_pattern_decision(
    engagement_id: str,
    pattern_id: str,
    payload: schemas.DecisionRecordUpsert,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Upsert of the singleton decision for this `(engagement, pattern)` pair —
    identity is fully in the path, so the request body carries no id.
    Creates the live decision if none exists yet (responds **201**), or
    updates the existing one in place (responds **200**); omitted fields
    leave an existing value unchanged. Enforces every rule in
    02-DATA-MODEL.md for a transition to `status: "approved"`: a selected
    target state belonging to this pattern, a rationale, an approver name, a
    decision date, and — when the selection is not the lowest
    `consumer_impact` among `candidates_considered` — both `forcing_perspective`
    and `forcing_rationale` justifying the deviation.
    """

    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")

    pattern = db.get(models.Pattern, pattern_id)
    if pattern is None:
        raise error(404, f"Pattern '{pattern_id}' not found", code="NOT_FOUND")

    existing = (
        db.query(models.DecisionRecord)
        .filter(
            models.DecisionRecord.engagement_id == engagement_id,
            models.DecisionRecord.pattern_id == pattern_id,
            models.DecisionRecord.status != "superseded",
        )
        .first()
    )

    _validate_decision(
        db,
        pattern_id=pattern_id,
        selected_target_state_id=payload.selected_target_state_id,
        candidates_considered=payload.candidates_considered,
        forcing_perspective=payload.forcing_perspective,
        forcing_rationale=payload.forcing_rationale,
        rationale=payload.rationale,
        approver_name=payload.approver_name,
        decision_date=payload.decision_date,
        status=payload.status,
    )

    if existing is None:
        decision = models.DecisionRecord(
            id=uuid.uuid4(),
            engagement_id=engagement_id,
            pattern_id=pattern_id,
            selected_target_state_id=payload.selected_target_state_id,
            candidates_considered=payload.candidates_considered,
            evaluation_notes=payload.evaluation_notes,
            forcing_perspective=payload.forcing_perspective,
            forcing_rationale=payload.forcing_rationale,
            rationale=payload.rationale,
            approver_name=payload.approver_name,
            approver_role=payload.approver_role,
            decision_date=payload.decision_date,
            status=payload.status,
        )
        db.add(decision)
        response.status_code = 201
    else:
        decision = existing
        _apply_decision_fields(decision, payload)

    db.commit()
    db.refresh(decision)
    return _decision_response(db, decision)


@router.get(
    "/decisions/{decision_id}",
    response_model=schemas.DecisionRecord,
    summary="Get a decision record by id",
    response_description="The decision record.",
    operation_id="get_decision",
    responses={404: _DECISION_NOT_FOUND},
)
def get_decision(
    decision_id: uuid.UUID,
    include_deleted: bool = Query(False, description="Return the record even if it is soft-deleted."),
    db: Session = Depends(get_db),
):

    decision = db.get(models.DecisionRecord, decision_id)
    if decision is None or (decision.deleted_at is not None and not include_deleted):
        raise error(404, f"Decision record '{decision_id}' not found", code="NOT_FOUND")
    return _decision_response(db, decision)


@router.put(
    "/decisions/{decision_id}",
    response_model=schemas.DecisionRecord,
    summary="Update a specific decision record by id",
    response_description="The updated decision record.",
    operation_id="update_decision",
    responses={404: _DECISION_NOT_FOUND, 422: _VALIDATION_FAILED},
)
def update_decision(
    decision_id: uuid.UUID, payload: schemas.DecisionRecordUpdate, db: Session = Depends(get_db)
):
    """
    Edits one specific record by its own id — including historical
    (superseded) ones, unlike the pattern-scoped upsert above, which only
    ever touches the live decision. Enforces the same approval rules as the
    upsert route.
    """

    decision = db.get(models.DecisionRecord, decision_id)
    if decision is None:
        raise error(404, f"Decision record '{decision_id}' not found", code="NOT_FOUND")

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
    new_forcing_perspective = (
        payload.forcing_perspective if payload.forcing_perspective is not None else decision.forcing_perspective
    )
    new_forcing_rationale = (
        payload.forcing_rationale if payload.forcing_rationale is not None else decision.forcing_rationale
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
        forcing_perspective=new_forcing_perspective,
        forcing_rationale=new_forcing_rationale,
        rationale=new_rationale,
        approver_name=new_approver_name,
        decision_date=new_decision_date,
        status=new_status,
    )

    _apply_decision_fields(decision, payload)

    db.commit()
    db.refresh(decision)
    return _decision_response(db, decision)


@router.post(
    "/decisions/{decision_id}/supersede",
    response_model=schemas.DecisionRecord,
    summary="Supersede a decision record",
    response_description="The now-superseded decision record.",
    operation_id="supersede_decision",
    responses={404: _DECISION_NOT_FOUND},
)
def supersede_decision(decision_id: uuid.UUID, db: Session = Depends(get_db)):
    """Sets `status = 'superseded'`, freeing the partial unique index so a
    new decision can be recorded for that (engagement, pattern)."""

    decision = db.get(models.DecisionRecord, decision_id)
    if decision is None:
        raise error(404, f"Decision record '{decision_id}' not found", code="NOT_FOUND")

    decision.status = "superseded"
    decision.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(decision)
    return _decision_response(db, decision)
