"""Engagement decisions on catalog items — 28-ITEM-AND-CONVERSION-MODEL.md
Part F.

Client-scoped: these routes write `engagement_decisions` only, never
`catalog_items` or `item_resolutions` (CLAUDE.md rule 9). One live decision
per (engagement, item); superseding frees the slot and keeps the history.

Validation carried over from the pattern decision records: approval needs a
resolution belonging to the item, a rationale, an approver and a date; and
choosing anything but the lowest `consumer_impact` needs the
`forcing_perspective` / `forcing_rationale` pair (25-STANDARDS-AND-VIEWPOINTS.md
A1). One change from the pattern records: "lowest" is judged across the
item's whole live resolution menu, not `candidates_considered`, which is kept
only as a record of what was presented at decision time.

Part U (app/items/coupling.py): an architecture decision drives others,
by resolution, as declared in the catalog's resolution_derivations.
Recording or superseding a leader's decision (wcf-service) re-derives its
dependents (the WCF host, internal NetTcp clients). A write to a derived
decision is a manual override: the decision becomes manual, keeps its link to
the leader, and is marked as overriding the derivation. An override whose
leading decision has since changed is flagged needs_review; writing it again
answers the flag. Superseding a dependent's decision re-derives it, so
superseding an override takes the derived decision. Derived decisions are
made by the platform, so the approval checks — written for a person's
decision — apply to a manual write only.

Every decision write ends by refreshing step 9's impact staleness
(app/impact/stale.py): impact computed for another decision is marked stale,
naming the resolution, until the next scan. That writes impact_summaries,
which is engagement data, not a master table.
"""

from typing import Annotated
import datetime
import uuid

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from app import models
from app.auth import activity, versions
from app.db import get_db
from app.errors import ErrorResponse, error, errors
from app.impact import stale as impact_stale
from app.items import coupling
from app.items import schemas as item_schemas
from app.schemas import CONSUMER_IMPACT_RANK

router = APIRouter(prefix="/api", tags=["Item Decisions"])

_VALIDATION_FAILED = {"model": ErrorResponse, "description": "A decision validation rule failed."}

# Substrings of `engagements.target_platform` that mean the engagement lands
# on Linux. Free text today, so this is a heuristic; "Azure Kubernetes
# Service" is deliberately absent because AKS also runs Windows node pools.
_LINUX_PLATFORM_MARKERS = ("linux", "openshift", "ocp")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def targets_linux(engagement: models.Engagement) -> bool:
    platform = (engagement.target_platform or "").lower()
    return any(marker in platform for marker in _LINUX_PLATFORM_MARKERS)


def _live_resolutions(db: Session, item_id: str) -> list[models.ItemResolution]:
    return (
        db.query(models.ItemResolution)
        .filter(
            models.ItemResolution.item_id == item_id,
            models.ItemResolution.deleted_at.is_(None),
            models.ItemResolution.status == "active",
        )
        .all()
    )


def decision_warnings(db: Session, decision: models.EngagementDecision) -> list[str]:
    if not decision.resolution_id:
        return []
    resolution = db.get(models.ItemResolution, decision.resolution_id)
    engagement = db.get(models.Engagement, decision.engagement_id)
    if resolution is not None and not resolution.linux_compatible and targets_linux(engagement):
        return [
            f"Resolution '{resolution.name}' is not Linux-compatible, but this engagement targets "
            f"'{engagement.target_platform}'."
        ]
    return []


def _link(db: Session, decision: models.EngagementDecision, follower: models.EngagementDecision) -> item_schemas.DecisionLink:
    """`decision` is one end of the dependency, `follower` the dependent
    decision: the derivation shown is the row for the resolution the
    follower was derived from or overridden against."""
    item = db.get(models.CatalogItem, decision.item_id)
    resolution = db.get(models.ItemResolution, decision.resolution_id) if decision.resolution_id else None
    row = coupling.derivation(db, follower.derived_against_resolution_id, follower.item_id)
    return item_schemas.DecisionLink(
        decision_id=str(decision.id), item_id=decision.item_id, item_name=item.name if item else decision.item_id,
        resolution_id=decision.resolution_id, resolution_name=resolution.name if resolution else None,
        status=decision.status, source=decision.source, derived_against_resolution_id=follower.derived_against_resolution_id,
        derivation_reason=row.reason if row else None, would_derive=_would_derive(db, follower),
        overrides_derivation=decision.overrides_derivation, needs_review=decision.needs_review,
    )


def _would_derive(db: Session, follower: models.EngagementDecision) -> str | None:
    """For an override: what the live leading decision would give it now
    (by name), or None when it gives nothing."""
    if not follower.overrides_derivation or follower.derived_from_decision_id is None:
        return None
    previous = db.get(models.EngagementDecision, follower.derived_from_decision_id)
    leader = coupling.live_decision(db, follower.engagement_id, previous.item_id) if previous else None
    row = coupling.derivation(db, leader.resolution_id if leader else None, follower.item_id)
    if row is None or row.action != "derive":
        return None
    resolution = db.get(models.ItemResolution, row.dependent_resolution_id)
    return resolution.name if resolution else row.dependent_resolution_id


def _response(db: Session, decision: models.EngagementDecision) -> item_schemas.EngagementDecisionOut:
    item = db.get(models.CatalogItem, decision.item_id)
    resolution = db.get(models.ItemResolution, decision.resolution_id) if decision.resolution_id else None
    leader = db.get(models.EngagementDecision, decision.derived_from_decision_id) if decision.derived_from_decision_id else None
    followers = (
        db.query(models.EngagementDecision)
        .filter(models.EngagementDecision.derived_from_decision_id == decision.id, models.EngagementDecision.status != "superseded")
        .order_by(models.EngagementDecision.item_id)
        .all()
    )
    return item_schemas.EngagementDecisionOut(
        source=decision.source,
        derived_from=_link(db, leader, decision) if leader else None,
        overrides_derivation=decision.overrides_derivation,
        needs_review=decision.needs_review,
        review_note=decision.review_note,
        followers=[_link(db, f, f) for f in followers],
        id=str(decision.id),
        engagement_id=decision.engagement_id,
        item_id=decision.item_id,
        item_name=item.name if item else decision.item_id,
        resolution_id=decision.resolution_id,
        resolution_name=resolution.name if resolution else None,
        candidates_considered=decision.candidates_considered,
        rationale=decision.rationale,
        forcing_perspective=decision.forcing_perspective,
        forcing_rationale=decision.forcing_rationale,
        evaluation_notes=decision.evaluation_notes,
        approver_name=decision.approver_name,
        approver_role=decision.approver_role,
        decision_date=decision.decision_date,
        status=decision.status,
        warnings=decision_warnings(db, decision),
        created_at=decision.created_at,
        updated_at=decision.updated_at,
        version=decision.version,
    )


def validate_decision(db: Session, item_id: str, decision: models.EngagementDecision) -> None:
    """Checks the decision's would-be state (after the payload is applied)."""
    problems: list[dict] = []

    resolution = None
    if decision.resolution_id:
        resolution = db.get(models.ItemResolution, decision.resolution_id)
        if resolution is None or resolution.deleted_at is not None:
            problems.append(
                {
                    "field": "resolution_id",
                    "message": f"Resolution '{decision.resolution_id}' does not exist.",
                    "code": "RESOLUTION_NOT_FOUND",
                }
            )
            resolution = None
        elif resolution.item_id != item_id:
            problems.append(
                {
                    "field": "resolution_id",
                    "message": f"Resolution '{resolution.id}' belongs to item '{resolution.item_id}', not '{item_id}'.",
                    "code": "RESOLUTION_WRONG_ITEM",
                }
            )
            resolution = None

    if decision.status == "approved":
        for field, code, what in (
            ("resolution_id", "APPROVAL_REQUIRES_SELECTION", "a selected resolution"),
            ("rationale", "APPROVAL_REQUIRES_RATIONALE", "a rationale"),
            ("approver_name", "APPROVAL_REQUIRES_APPROVER", "an approver name"),
            ("decision_date", "APPROVAL_REQUIRES_DATE", "a decision date"),
        ):
            if not getattr(decision, field):
                problems.append({"field": field, "message": f"An approved decision requires {what}.", "code": code})

        menu = _live_resolutions(db, item_id)
        if resolution is not None and menu:
            lowest = min(menu, key=lambda r: CONSUMER_IMPACT_RANK[r.consumer_impact])
            if CONSUMER_IMPACT_RANK[resolution.consumer_impact] > CONSUMER_IMPACT_RANK[lowest.consumer_impact]:
                message = (
                    f"{resolution.name} has higher consumer impact ({resolution.consumer_impact}) than the "
                    f"lowest option {lowest.name} ({lowest.consumer_impact}). Both forcing_perspective and "
                    "forcing_rationale are required to justify the deviation."
                )
                problems += [
                    {"field": field, "message": message, "code": "FORCING_PERSPECTIVE_AND_RATIONALE_REQUIRED"}
                    for field in ("forcing_perspective", "forcing_rationale")
                    if not getattr(decision, field)
                ]

    if problems:
        raise errors(422, problems)


def _live_decision(db: Session, engagement_id: str, item_id: str, lock: bool = False) -> models.EngagementDecision | None:
    query = (
        db.query(models.EngagementDecision)
        .filter(
            models.EngagementDecision.engagement_id == engagement_id,
            models.EngagementDecision.item_id == item_id,
            models.EngagementDecision.status != "superseded",
        )
    )
    return (query.with_for_update() if lock else query).first()


@router.get(
    "/engagements/{engagement_id}/item-decisions",
    response_model=list[item_schemas.EngagementDecisionOut],
    summary="List an engagement's item decisions",
    operation_id="list_engagement_item_decisions",
    responses={404: {"model": ErrorResponse, "description": "No engagement exists with this id."}},
)
def list_item_decisions(engagement_id: str, db: Session = Depends(get_db)):
    if db.get(models.Engagement, engagement_id) is None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    decisions = (
        db.query(models.EngagementDecision)
        .filter(models.EngagementDecision.engagement_id == engagement_id)
        .order_by(models.EngagementDecision.item_id, models.EngagementDecision.created_at)
        .all()
    )
    return [_response(db, d) for d in decisions]


@router.get(
    "/engagements/{engagement_id}/items/{item_id}/decision",
    response_model=item_schemas.EngagementDecisionOut,
    summary="Get the live decision for an item in an engagement",
    operation_id="get_engagement_item_decision",
    responses={404: {"model": ErrorResponse, "description": "No live decision for this (engagement, item) pair."}},
)
def get_item_decision(engagement_id: str, item_id: str, db: Session = Depends(get_db)):
    decision = _live_decision(db, engagement_id, item_id)
    if decision is None:
        raise error(404, f"No live decision for item '{item_id}' in engagement '{engagement_id}'", code="NOT_FOUND")
    return _response(db, decision)


@router.put(
    "/engagements/{engagement_id}/items/{item_id}/decision",
    response_model=item_schemas.EngagementDecisionOut,
    summary="Record or update the decision for an item in an engagement",
    operation_id="upsert_engagement_item_decision",
    responses={
        404: {"model": ErrorResponse, "description": "No engagement or item exists with these ids."},
        422: _VALIDATION_FAILED,
    },
)
def upsert_item_decision(
    engagement_id: str,
    item_id: str,
    payload: item_schemas.EngagementDecisionUpsert,
    response: Response,
    db: Session = Depends(get_db),
    if_match: Annotated[str | None, Header(description="The version of the decision the edit was made on; 0 when "
                                                            "there was none. A stale copy is refused (409 STALE_COPY).")] = None,
):
    """Creates the live decision (201) or updates it in place (200). An
    omitted field keeps its current value; a field sent as `null` is cleared
    (so a decision moved back to the lowest-impact resolution can drop its
    forcing perspective and rationale). The result is validated as a whole,
    so clearing something an approval needs is rejected. A Linux-incompatible
    resolution on a Linux-targeted engagement is allowed, and reported in
    `warnings`."""
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    item = db.get(models.CatalogItem, item_id)
    if item is None or item.deleted_at is not None:
        raise error(404, f"Catalog item '{item_id}' not found", code="NOT_FOUND")

    decision = _live_decision(db, engagement_id, item_id, lock=True)
    versions.check(db, decision.version if decision else None, if_match, "item_decision",
                   decision.id if decision else None, "this decision")
    created = decision is None
    if created:
        decision = models.EngagementDecision(
            id=uuid.uuid4(), engagement_id=engagement_id, item_id=item_id, status="pending"
        )
    # exclude_unset: only fields present in the body. A present null clears
    # the field; an absent field is left alone.
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(decision, field, value)
    # A person writing a derived decision overrides the derivation (Part U):
    # it becomes theirs, and stays linked to the decision it would follow.
    if decision.source == "derived":
        decision.source = "manual"
        decision.overrides_derivation = True
    # Any write by a person answers a review flag: the override now stands
    # against the current leading decision.
    if decision.overrides_derivation:
        coupling.rebaseline_override(db, decision)

    # Validate before the row joins the session, so a rejected create
    # leaves nothing behind to autoflush.
    validate_decision(db, item_id, decision)
    decision.updated_at = _now()
    if created:
        db.add(decision)
        response.status_code = 201
    else:
        decision.version += 1
    db.flush()
    activity.about("item_decision", decision.id)
    # A leader's decision re-derives its followers in the same transaction.
    coupling.rederive(db, engagement_id, item_id)
    # Step 9's impact computed for another decision is stale until the next
    # scan (33-IMPACT-ANALYSIS Part C) — this item's and any follower's.
    impact_stale.refresh(db, engagement_id)
    db.commit()
    db.refresh(decision)
    return _response(db, decision)


@router.get(
    "/repositories/{repository_id}/work-list-decisions",
    response_model=item_schemas.WorkListDecisionsOut,
    summary="Get the decisions behind a repository's work list",
    operation_id="get_repository_work_list_decisions",
    responses={404: {"model": ErrorResponse, "description": "No repository exists with this id."}},
)
def get_work_list_decisions(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    """For each item found in the repository: the engagement's live decision
    (with what it follows and what follows it, Part U). Per project: items
    subsumed (or explicitly not subsumed) by another item's decision on the
    same project, and for a dependent item, what its leader's decision means
    there — derived, not derived and why, an internal client or not."""
    repository = db.get(models.Repository, repository_id)
    if repository is None or repository.deleted_at is not None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")
    engagement_id = repository.engagement_id

    found: dict[uuid.UUID, set[str]] = {}
    for occurrence in db.query(models.ItemOccurrence).filter(
            models.ItemOccurrence.repository_id == repository_id, models.ItemOccurrence.detection_state == "found"):
        found.setdefault(occurrence.project_id, set()).add(occurrence.item_id)
    items = sorted({i for ids in found.values() for i in ids})

    decisions = {}
    for item_id in items:
        decision = coupling.live_decision(db, engagement_id, item_id)
        if decision is not None:
            decisions[item_id] = _response(db, decision)

    projects = []
    for project_id, project_items in sorted(found.items(), key=lambda p: str(p[0])):
        notes: dict[str, item_schemas.WorkListItemNote] = {}
        for item_id, subsumption in coupling.subsumptions(db, engagement_id, project_items).items():
            if subsumption["action"] == "subsume":
                notes[item_id] = item_schemas.WorkListItemNote(subsumed_by=subsumption)
            else:
                notes[item_id] = item_schemas.WorkListItemNote(
                    follows=subsumption["item_id"], action="not_subsumed", applies=False,
                    note=f"Not subsumed by the {subsumption['item_id']} decision ({subsumption['resolution_name']}): "
                         f"{subsumption['reason']}")
        for item_id in sorted(project_items):
            for leader_item_id in coupling.leaders_of(db, item_id):
                note = _dependent_note(db, engagement_id, project_id, item_id, leader_item_id)
                if note is not None:
                    current = notes.get(item_id) or item_schemas.WorkListItemNote()
                    notes[item_id] = current.model_copy(update=note)
        projects.append(item_schemas.WorkListProjectNotes(project_id=str(project_id), items=notes))

    return item_schemas.WorkListDecisionsOut(engagement_id=engagement_id, decisions=decisions, projects=projects)


def _dependent_note(db: Session, engagement_id: str, project_id: uuid.UUID, item_id: str, leader_item_id: str) -> dict | None:
    """What the leader's live decision means for this dependent on this project."""
    leader = coupling.live_decision(db, engagement_id, leader_item_id)
    if leader is None or not leader.resolution_id:
        if not coupling.derives_anything(db, leader_item_id, item_id):
            return None
        return {"follows": leader_item_id, "action": None, "applies": None,
                "note": f"Follows the {leader_item_id} decision once it is decided, where its resolution settles this item."}
    resolution = db.get(models.ItemResolution, leader.resolution_id)
    chosen = f"the {leader_item_id} decision ({resolution.name if resolution else leader.resolution_id})"
    row = coupling.derivation(db, leader.resolution_id, item_id)
    if row is None:
        return {"follows": leader_item_id, "action": None, "applies": False,
                "note": f"Not derived: {chosen} declares nothing for this item. Decide it on its own."}
    if row.action == "not_derived":
        return {"follows": leader_item_id, "action": row.action, "applies": False,
                "note": f"Not derived: {chosen} does not settle this item. {row.reason}"}
    if row.applies_to == "internal_clients":
        services = sorted({c["service_project"] for c in coupling.internal_clients(db, engagement_id, item_id, leader_item_id)
                           if c["client_project_id"] == str(project_id)})
        if not services:
            return {"follows": leader_item_id, "action": row.action, "applies": False,
                    "note": f"Calls no {leader_item_id} inside this migration, so {chosen} does not apply to this project — "
                            "a service owned elsewhere is a conversation with its owner. Decide it on its own."}
        return {"follows": leader_item_id, "action": row.action, "applies": True,
                "note": f"Internal client of {', '.join(services)}: follows {chosen}. {row.reason}"}
    return {"follows": leader_item_id, "action": row.action, "applies": True, "note": f"Follows {chosen}. {row.reason}"}


@router.post(
    "/item-decisions/{decision_id}/supersede",
    response_model=item_schemas.EngagementDecisionOut,
    summary="Supersede an item decision",
    operation_id="supersede_item_decision",
    responses={404: {"model": ErrorResponse, "description": "No decision exists with this id."}},
)
def supersede_item_decision(
    decision_id: uuid.UUID, db: Session = Depends(get_db),
    if_match: Annotated[str | None, Header(description="The version superseded; a stale copy is refused (409 STALE_COPY).")] = None,
):
    decision = versions.locked(db, models.EngagementDecision, decision_id)
    if decision is None:
        raise error(404, f"Decision '{decision_id}' not found", code="NOT_FOUND")
    versions.check(db, decision.version, if_match, "item_decision", decision.id, "this decision")
    decision.version += 1
    decision.status = "superseded"
    decision.updated_at = _now()
    db.flush()
    # A superseded leader leaves its derived dependents nothing to follow,
    # and flags its overrides for review.
    coupling.rederive(db, decision.engagement_id, decision.item_id)
    # A superseded dependent takes what its leaders derive, if anything —
    # superseding an override returns to the derived decision.
    coupling.rederive_leaders_of(db, decision.engagement_id, decision.item_id)
    impact_stale.refresh(db, decision.engagement_id)
    db.commit()
    db.refresh(decision)
    return _response(db, decision)
