"""The human-gate queue — 27-PATTERN-VALIDATION.md Part E.

**Generic across gate types.** Nothing here knows what a pattern candidate
is; step 6 is simply the first `item_type` to appear. Steps 22, 38 and 50
raise items with different types and payloads and get these endpoints, the
summary and the queue UI unchanged.

Deciding an item does **not** resume the job. Resume is explicit, via the
existing execution endpoint. Keeping them separate is what lets a reviewer
work through twenty items without triggering twenty resumes.
"""

import datetime
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error

router = APIRouter(tags=["Validation Queue"])

_ITEM_NOT_FOUND = {"model": ErrorResponse, "description": "No queue item exists with this id."}
_NOT_OPEN = {"model": ErrorResponse, "description": "The item is not open — it has already been decided, superseded or withdrawn."}


class QueueItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    engagement_id: str
    job_execution_id: uuid.UUID = Field(description="The execution that raised this item. An item outlives it — that is the point of a gate.")
    step_execution_id: uuid.UUID
    step_name: str
    item_type: str
    item_key: str = Field(description="Natural key of the subject — the cluster_id for pattern_candidate items.")
    title: str
    payload: dict = Field(description="Type-specific detail for the UI. Opaque to this router.")
    status: str
    outcome: str | None
    outcome_detail: dict | None
    decision_note: str | None
    decided_by: str | None
    decided_at: datetime.datetime | None
    is_deferred: bool = Field(description="Open, but set aside until the evidence improves. Deferred items do not block their gate.")
    deferred_until_coverage: float | None
    deferred_until_member_count: int | None
    priority: int
    created_at: datetime.datetime


class DecideRequest(BaseModel):
    outcome: str = Field(description="Type-specific decision value. For pattern_candidate: create_pattern, merge_into_pattern or reject.")
    outcome_detail: dict[str, Any] | None = Field(default=None, description="Structured decision data, e.g. {\"pattern_id\": \"msmq-integration-library\"}.")
    note: str | None = Field(default=None, description="Rationale. Mandatory for outcomes that discard a subject, such as reject.")
    decided_by: str = Field(description="Free text until auth exists.")


class DeferRequest(BaseModel):
    until_coverage: float | None = Field(default=None, ge=0, le=1, description="Resurface once estate coverage reaches this ratio.")
    until_member_count: int | None = Field(default=None, ge=1, description="Resurface once the subject has at least this many members.")
    note: str | None = None
    deferred_by: str | None = None


class QueueSummaryGroup(BaseModel):
    step_name: str
    item_type: str
    open_count: int = Field(description="Open and not deferred — what actually blocks a gate.")
    deferred_count: int
    decided_count: int


class QueueSummaryOut(BaseModel):
    engagement_id: str
    open_count: int
    deferred_count: int
    decided_count: int
    superseded_count: int
    withdrawn_count: int
    by_step: list[QueueSummaryGroup]
    blocked_executions: list[dict] = Field(description="Executions in STOPPED/AWAITING_APPROVAL and how many open items block each.")


# Outcomes that throw away a subject owe an explanation. Per-type rather
# than global: a gate whose outcomes are all benign should not be forced to
# collect a note it does not need.
_NOTE_REQUIRED_OUTCOMES = {"pattern_candidate": {"reject"}}


def _item_out(item: models.ValidationQueueItem) -> QueueItemOut:
    return QueueItemOut(
        id=item.id,
        engagement_id=item.engagement_id,
        job_execution_id=item.job_execution_id,
        step_execution_id=item.step_execution_id,
        step_name=item.step_name,
        item_type=item.item_type,
        item_key=item.item_key,
        title=item.title,
        payload=item.payload,
        status=item.status,
        outcome=item.outcome,
        outcome_detail=item.outcome_detail,
        decision_note=item.decision_note,
        decided_by=item.decided_by,
        decided_at=item.decided_at,
        is_deferred=item.is_deferred,
        deferred_until_coverage=float(item.deferred_until_coverage) if item.deferred_until_coverage is not None else None,
        deferred_until_member_count=item.deferred_until_member_count,
        priority=item.priority,
        created_at=item.created_at,
    )


@router.get(
    "/api/engagements/{engagement_id}/validation-queue",
    response_model=list[QueueItemOut],
    summary="Queue items for an engagement",
    response_description="Matching items, blocking ones first, then by priority and age.",
    operation_id="list_validation_queue",
)
def list_queue(
    engagement_id: str,
    status: str | None = Query(default=None, description="open, decided, superseded or withdrawn."),
    item_type: str | None = Query(default=None),
    step_name: str | None = Query(default=None),
    include_deferred: bool = Query(default=False, description="Deferred items are hidden by default — they were consciously set aside."),
    db: Session = Depends(get_db),
):
    stmt = select(models.ValidationQueueItem).where(models.ValidationQueueItem.engagement_id == engagement_id)
    if status:
        stmt = stmt.where(models.ValidationQueueItem.status == status)
    if item_type:
        stmt = stmt.where(models.ValidationQueueItem.item_type == item_type)
    if step_name:
        stmt = stmt.where(models.ValidationQueueItem.step_name == step_name)
    if not include_deferred:
        stmt = stmt.where(models.ValidationQueueItem.deferred_at.is_(None))

    items = db.scalars(
        stmt.order_by(models.ValidationQueueItem.priority, models.ValidationQueueItem.created_at)
    ).all()
    return [_item_out(i) for i in items]


@router.get(
    "/api/engagements/{engagement_id}/validation-queue/summary",
    response_model=QueueSummaryOut,
    summary="What is waiting, and what it blocks",
    response_description="Counts by status and step, plus the executions currently held open.",
    operation_id="validation_queue_summary",
)
def queue_summary(engagement_id: str, db: Session = Depends(get_db)):
    """
    The cross-cutting view the Workflow tab's "pending approvals" renders.
    `open_count` deliberately excludes deferred items: it is meant to answer
    "how much is blocking me", and a deferred item is by definition not.
    """
    rows = db.execute(
        select(
            models.ValidationQueueItem.step_name,
            models.ValidationQueueItem.item_type,
            models.ValidationQueueItem.status,
            models.ValidationQueueItem.deferred_at,
            func.count().label("n"),
        )
        .where(models.ValidationQueueItem.engagement_id == engagement_id)
        .group_by(
            models.ValidationQueueItem.step_name,
            models.ValidationQueueItem.item_type,
            models.ValidationQueueItem.status,
            models.ValidationQueueItem.deferred_at,
        )
    ).all()

    groups: dict[tuple[str, str], QueueSummaryGroup] = {}
    totals = {"open": 0, "deferred": 0, "decided": 0, "superseded": 0, "withdrawn": 0}
    for step_name, item_type, status, deferred_at, n in rows:
        key = (step_name, item_type)
        group = groups.setdefault(
            key, QueueSummaryGroup(step_name=step_name, item_type=item_type, open_count=0, deferred_count=0, decided_count=0)
        )
        if status == "open" and deferred_at is not None:
            group.deferred_count += n
            totals["deferred"] += n
        elif status == "open":
            group.open_count += n
            totals["open"] += n
        elif status == "decided":
            group.decided_count += n
            totals["decided"] += n
        else:
            totals[status] += n

    blocked = db.execute(
        select(
            models.ValidationQueueItem.job_execution_id,
            models.WfJobExecution.batch_status,
            models.WfJobExecution.exit_status,
            func.count().label("n"),
        )
        .join(models.WfJobExecution, models.WfJobExecution.id == models.ValidationQueueItem.job_execution_id)
        .where(models.ValidationQueueItem.engagement_id == engagement_id)
        .where(models.ValidationQueueItem.status == "open")
        .where(models.ValidationQueueItem.deferred_at.is_(None))
        .where(models.WfJobExecution.batch_status == "STOPPED")
        .group_by(models.ValidationQueueItem.job_execution_id, models.WfJobExecution.batch_status, models.WfJobExecution.exit_status)
    ).all()

    return QueueSummaryOut(
        engagement_id=engagement_id,
        open_count=totals["open"],
        deferred_count=totals["deferred"],
        decided_count=totals["decided"],
        superseded_count=totals["superseded"],
        withdrawn_count=totals["withdrawn"],
        by_step=sorted(groups.values(), key=lambda g: (g.step_name, g.item_type)),
        blocked_executions=[
            {"job_execution_id": str(eid), "batch_status": bs, "exit_status": es, "open_item_count": n}
            for eid, bs, es, n in blocked
        ],
    )


@router.get(
    "/api/validation-queue/{item_id}",
    response_model=QueueItemOut,
    summary="One queue item",
    operation_id="get_validation_queue_item",
    responses={404: _ITEM_NOT_FOUND},
)
def get_item(item_id: uuid.UUID, db: Session = Depends(get_db)):
    item = db.get(models.ValidationQueueItem, item_id)
    if item is None:
        raise error(404, f"No queue item '{item_id}'", code="NOT_FOUND")
    return _item_out(item)


@router.post(
    "/api/validation-queue/{item_id}/decide",
    response_model=QueueItemOut,
    summary="Record a decision on a queue item",
    response_description="The decided item.",
    operation_id="decide_validation_queue_item",
    responses={404: _ITEM_NOT_FOUND, 409: _NOT_OPEN, 422: {"model": ErrorResponse, "description": "The outcome is not valid for this item type, or a mandatory note is missing."}},
)
def decide_item(item_id: uuid.UUID, payload: DecideRequest, db: Session = Depends(get_db)):
    """
    Records the human's answer. It does **not** apply it and does **not**
    resume the job.

    Applying is the step's job, on the next resume — that keeps every
    cluster mutation auditable to a specific job execution, and means a
    decision made while no execution is running is picked up rather than
    lost. Resuming is explicit for a plainer reason: a reviewer working
    through twenty items should not fire twenty resumes.
    """
    item = db.get(models.ValidationQueueItem, item_id)
    if item is None:
        raise error(404, f"No queue item '{item_id}'", code="NOT_FOUND")
    if item.status != "open":
        raise error(409, f"Item is '{item.status}', not open", code="NOT_OPEN")

    if payload.outcome in _NOTE_REQUIRED_OUTCOMES.get(item.item_type, set()) and not (payload.note or "").strip():
        raise error(422, f"Outcome '{payload.outcome}' requires a note", code="NOTE_REQUIRED", field="note")

    item.status = "decided"
    item.outcome = payload.outcome
    item.outcome_detail = payload.outcome_detail
    item.decision_note = payload.note
    item.decided_by = payload.decided_by
    item.decided_at = datetime.datetime.now(datetime.timezone.utc)
    # Deciding clears any deferral: the question has been answered, so there
    # is nothing left to resurface.
    item.deferred_at = None
    item.deferred_until_coverage = None
    item.deferred_until_member_count = None
    db.commit()
    db.refresh(item)
    return _item_out(item)


@router.post(
    "/api/validation-queue/{item_id}/defer",
    response_model=QueueItemOut,
    summary="Set an item aside until the evidence improves",
    response_description="The deferred item, still open.",
    operation_id="defer_validation_queue_item",
    responses={404: _ITEM_NOT_FOUND, 409: _NOT_OPEN, 422: {"model": ErrorResponse, "description": "No threshold given."}},
)
def defer_item(item_id: uuid.UUID, payload: DeferRequest, db: Session = Depends(get_db)):
    """
    At 24% coverage the honest answer to a thin cluster is often "ask me
    again later". Without defer, a reviewer is forced into a premature
    reject that the re-review trigger then has to undo.

    The item stays `open` — the subject still needs an answer — but stops
    blocking its gate and is hidden from the default queue until a
    threshold is met. A deferral with no threshold would be indefinite
    silence, so one is required.
    """
    item = db.get(models.ValidationQueueItem, item_id)
    if item is None:
        raise error(404, f"No queue item '{item_id}'", code="NOT_FOUND")
    if item.status != "open":
        raise error(409, f"Item is '{item.status}', not open", code="NOT_OPEN")
    if payload.until_coverage is None and payload.until_member_count is None:
        raise error(
            422,
            "A deferral needs until_coverage or until_member_count — otherwise nothing can resurface it",
            code="THRESHOLD_REQUIRED",
        )

    item.deferred_at = datetime.datetime.now(datetime.timezone.utc)
    item.deferred_until_coverage = payload.until_coverage
    item.deferred_until_member_count = payload.until_member_count
    if payload.note:
        item.decision_note = payload.note
    if payload.deferred_by:
        item.decided_by = payload.deferred_by
    db.commit()
    db.refresh(item)
    return _item_out(item)
