import datetime
from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_db
from app.engagements import service as engagement_service
from app.errors import ErrorResponse, error
from app.workflow import registration
from app.workflow.runtime import service as runtime_service
from app.workflow.runtime.schemas import JobExecutionOut
from app.workflow.schemas import ViewpointCoverage

router = APIRouter(prefix="/api/engagements", tags=["Engagements"])

_NOT_FOUND = {"model": ErrorResponse, "description": "No engagement exists with this id (or it is soft-deleted and `include_deleted` was not set)."}


@router.get(
    "",
    response_model=list[schemas.Engagement],
    summary="List engagements",
    response_description="Engagements ordered by id.",
    operation_id="list_engagements",
)
def list_engagements(
    include_deleted: bool = Query(False, description="Include soft-deleted engagements."),
    db: Session = Depends(get_db),
):
    query = db.query(models.Engagement)
    if not include_deleted:
        query = query.filter(models.Engagement.deleted_at.is_(None))
    return query.order_by(models.Engagement.id).all()


@router.post(
    "",
    response_model=schemas.Engagement,
    status_code=201,
    summary="Create an engagement",
    response_description="The newly created engagement.",
    operation_id="create_engagement",
    responses={
        409: {"model": ErrorResponse, "description": "An engagement with this id already exists."},
        422: {"model": ErrorResponse, "description": "The id, client name or target framework is not valid."},
    },
)
def create_engagement(payload: schemas.EngagementCreate, db: Session = Depends(get_db)):
    try:
        engagement = engagement_service.create(
            db, payload.id, payload.client_name, payload.target_framework, description=payload.description,
            target_platform=payload.target_platform, default_posture=payload.default_posture,
        )
    except engagement_service.EngagementError as e:
        raise error(e.status_code, str(e), field=e.field, code=e.code)
    db.commit()
    db.refresh(engagement)
    return engagement


@router.get(
    "/{engagement_id}",
    response_model=schemas.Engagement,
    summary="Get an engagement",
    response_description="The engagement.",
    operation_id="get_engagement",
    responses={404: _NOT_FOUND},
)
def get_engagement(
    engagement_id: str,
    include_deleted: bool = Query(False, description="Return the engagement even if it is soft-deleted."),
    db: Session = Depends(get_db),
):
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None or (engagement.deleted_at is not None and not include_deleted):
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    return engagement


@router.put(
    "/{engagement_id}",
    response_model=schemas.Engagement,
    summary="Update an engagement",
    response_description="The updated engagement.",
    operation_id="update_engagement",
    responses={404: _NOT_FOUND},
)
def update_engagement(
    engagement_id: str, payload: schemas.EngagementUpdate, db: Session = Depends(get_db)
):
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")

    engagement.client_name = payload.client_name
    engagement.description = payload.description
    engagement.target_platform = payload.target_platform
    engagement.default_posture = payload.default_posture
    engagement.target_framework = payload.target_framework
    if payload.status is not None:
        engagement.status = payload.status
    engagement.updated_at = datetime.datetime.now(datetime.timezone.utc)

    db.commit()
    db.refresh(engagement)
    return engagement


@router.get(
    "/{engagement_id}/coverage",
    response_model=schemas.CoverageSummary,
    summary="Get decision-record coverage for an engagement",
    response_description="Pattern and decision counts for this engagement, for the future dashboard.",
    operation_id="get_engagement_coverage",
    responses={404: _NOT_FOUND},
)
def get_engagement_coverage(engagement_id: str, db: Session = Depends(get_db)):
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    return compute_coverage(db, engagement_id)


def compute_coverage(db: Session, engagement_id: str) -> schemas.CoverageSummary:
    """Shared with the dashboard (`GET /api/engagements/{eid}/dashboard`) so
    its decision counts match this endpoint exactly, by construction —
    16-DASHBOARD-SPEC.md's acceptance criterion. Caller is responsible for
    the engagement-exists check."""
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

    # 25-STANDARDS-AND-VIEWPOINTS.md Part A1 — the programme-level rollup a
    # free-text forcing_factor could never answer: "of N deviations from
    # lift-and-shift, how many were security-driven?"
    perspective_breakdown = dict(
        Counter(
            d.forcing_perspective
            for d in live_decisions
            if d.forcing_perspective and d.pattern_id in counted_pattern_ids
        )
    )

    return schemas.CoverageSummary(
        engagement_id=engagement_id,
        total_patterns=len(counted_pattern_ids),
        approved=approved,
        in_review=in_review,
        parked=parked,
        deferred=len(deferred_pattern_ids),
        patterns_without_decision=patterns_without_decision,
        perspective_breakdown=perspective_breakdown,
    )


@router.get(
    "/{engagement_id}/viewpoint-coverage",
    response_model=ViewpointCoverage,
    summary="Get architecture-viewpoint coverage for an engagement",
    response_description="Per-viewpoint contributing steps, implemented count, ran count, and a coverage label.",
    operation_id="get_engagement_viewpoint_coverage",
    responses={404: _NOT_FOUND},
)
def get_engagement_viewpoint_coverage(engagement_id: str, db: Session = Depends(get_db)):
    """
    25-STANDARDS-AND-VIEWPOINTS.md Part A2 — honest scoping over implying
    complete coverage. `total_contributing`/`implemented_count` are catalog
    facts (which steps map to this viewpoint, how many are built);
    `ran_count` is scoped to this one engagement's own executions.
    """
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    return registration.viewpoint_coverage(db, engagement_id)


@router.get(
    "/{engagement_id}/executions",
    response_model=list[JobExecutionOut],
    summary="List workflow executions for an engagement",
    response_description="Executions whose job instance declares engagement_id matching this engagement, newest first.",
    operation_id="list_engagement_executions",
    tags=["Engagements", "Workflow Executions"],
    responses={404: _NOT_FOUND},
)
def list_engagement_executions(
    engagement_id: str,
    job_name: str | None = Query(None, description="Filter to one job definition, e.g. 'phase0-repository-discovery'."),
    batch_status: str | None = Query(None, description="Filter by batch status, e.g. 'COMPLETED' or 'FAILED'."),
    limit: int = Query(50, ge=1, le=500, description="Maximum executions to return."),
    offset: int = Query(0, ge=0, description="Number of executions to skip, for paging."),
    db: Session = Depends(get_db),
):
    """
    A convenience, engagement-scoped view over `GET /api/workflow/executions`
    — the same data, pre-filtered. Only matches jobs whose parameters
    actually declare `engagement_id` (most do; a wave-scoped job in a future
    track might not).
    """
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")

    executions = runtime_service.list_executions(
        db,
        job_name=job_name,
        batch_status=batch_status,
        engagement_id=engagement_id,
        limit=limit,
        offset=offset,
    )
    return [runtime_service.to_execution_out(db, e) for e in executions]
