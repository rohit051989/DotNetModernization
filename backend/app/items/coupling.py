"""Decision coupling — 28-ITEM-AND-CONVERSION-MODEL.md Part U.

Architecture decisions drive others. What each leading resolution means for
each dependent item is master catalog data, `resolution_derivations`,
authored beside the resolution in catalog_items.yaml (app/items/derivations.py
loads it). Derivation is by resolution, not by item: CoreWCF and a REST
rewrite of the same wcf-service mean different things for its clients.

- **derive.** The dependent's decision is created or kept in step with
  `source = 'derived'`, `derived_from_decision_id` the leader and
  `derived_against_resolution_id` the leader's resolution. Its status follows
  the leader's (an approved leader approves the consequence, approver and
  date copied, forcing pair carried). `applies_to = 'internal_clients'`
  derives only where the engagement has an internal client of the service: a
  project carrying the dependent whose integration edges (lifecycle step 11)
  reach a project carrying the leader.
- **not_derived.** The leading decision does not settle the dependent. A
  derived decision is superseded; the item is awaiting_decision, and the work
  list explains why from the row's reason.
- **subsume / not_subsumed.** A dependent on the leader's own project is, or
  is not, further work. Computed when the work list is read; nothing written.
- **Overrides.** A derived decision written by hand becomes `manual`, keeps
  the link and sets `overrides_derivation`. A manual decision already in
  place when a derivation applies is never overwritten — it is linked and
  marked as overriding. When the leading decision changes (another
  resolution, another decision, or superseded), an override was made against
  a decision that no longer stands: it is flagged `needs_review`, naming the
  old and new leading decisions, never kept or discarded silently. Writing
  the decision again clears the flag.

Derived decisions are written only to `engagement_decisions` (CLAUDE.md rule
9: client-scoped writes never touch the master catalog).
"""

import datetime
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models

DECISION_ACTIONS = ("derive", "not_derived")
SUBSUMPTION_ACTIONS = ("subsume", "not_subsumed")


def _live_rows(db: Session):
    return db.query(models.ResolutionDerivation).filter(models.ResolutionDerivation.deleted_at.is_(None))


def derivation(db: Session, resolution_id: str | None, dependent_item_id: str) -> models.ResolutionDerivation | None:
    """The live row for (leading resolution, dependent item), if declared."""
    if not resolution_id:
        return None
    row = db.get(models.ResolutionDerivation, (resolution_id, dependent_item_id))
    return row if row is not None and row.deleted_at is None else None


def leader_items(db: Session) -> list[str]:
    return sorted({row.item_id for row in _live_rows(db)})


def dependents_of(db: Session, leader_item_id: str, actions: tuple[str, ...] = DECISION_ACTIONS) -> list[str]:
    return sorted({row.dependent_item_id for row in _live_rows(db).filter(
        models.ResolutionDerivation.item_id == leader_item_id, models.ResolutionDerivation.action.in_(actions))})


def leaders_of(db: Session, dependent_item_id: str, actions: tuple[str, ...] = DECISION_ACTIONS) -> list[str]:
    return sorted({row.item_id for row in _live_rows(db).filter(
        models.ResolutionDerivation.dependent_item_id == dependent_item_id, models.ResolutionDerivation.action.in_(actions))})


def derives_anything(db: Session, leader_item_id: str, dependent_item_id: str) -> bool:
    """Whether any of the leader's resolutions derives a decision for the dependent."""
    return _live_rows(db).filter(
        models.ResolutionDerivation.item_id == leader_item_id, models.ResolutionDerivation.dependent_item_id == dependent_item_id,
        models.ResolutionDerivation.action == "derive").first() is not None


def live_decision(db: Session, engagement_id: str, item_id: str) -> models.EngagementDecision | None:
    return (
        db.query(models.EngagementDecision)
        .filter(models.EngagementDecision.engagement_id == engagement_id, models.EngagementDecision.item_id == item_id,
                models.EngagementDecision.status != "superseded")
        .first()
    )


def internal_clients(db: Session, engagement_id: str, follower: str, leader: str) -> list[dict]:
    """Projects carrying `follower` whose integration edges reach a project
    carrying `leader`: [{client_project_id, client_project, service_project_id, service_project}]."""
    rows = db.execute(text("""
        select distinct e.caller_project_id, pc.relative_path, e.callee_project_id, ps.relative_path
        from integration_edges e
        join item_occurrences c on c.project_id = e.caller_project_id and c.item_id = :follower and c.detection_state = 'found'
        join item_occurrences s on s.project_id = e.callee_project_id and s.item_id = :leader and s.detection_state = 'found'
        join projects pc on pc.id = e.caller_project_id
        join projects ps on ps.id = e.callee_project_id
        where e.engagement_id = :engagement
        order by 2, 4
    """), {"follower": follower, "leader": leader, "engagement": engagement_id}).all()
    return [{"client_project_id": str(a), "client_project": b, "service_project_id": str(c), "service_project": d} for a, b, c, d in rows]


def _live_resolution_ids(db: Session, item_id: str) -> list[str]:
    return sorted(
        r.id for r in db.query(models.ItemResolution).filter(
            models.ItemResolution.item_id == item_id, models.ItemResolution.deleted_at.is_(None),
            models.ItemResolution.status == "active")
    )


def _resolution_name(db: Session, resolution_id: str | None) -> str | None:
    if not resolution_id:
        return None
    resolution = db.get(models.ItemResolution, resolution_id)
    return resolution.name if resolution else resolution_id


def target_for(db: Session, engagement_id: str, leader: models.EngagementDecision | None, dependent_item_id: str) -> str | None:
    """The resolution the leader's decision derives for the dependent, or
    None when it derives nothing (no decision or choice yet, not_derived, a
    subsumption, nothing declared, or an internal-clients row with none)."""
    row = derivation(db, leader.resolution_id if leader else None, dependent_item_id)
    if row is None or row.action != "derive":
        return None
    if row.applies_to == "internal_clients" and not internal_clients(db, engagement_id, dependent_item_id, leader.item_id):
        return None
    return row.dependent_resolution_id


def review_note(db: Session, follower: models.EngagementDecision, leader_item_id: str,
                leader: models.EngagementDecision | None) -> str:
    leader_item = db.get(models.CatalogItem, leader_item_id)
    leader_name = leader_item.name if leader_item else leader_item_id
    old = _resolution_name(db, follower.derived_against_resolution_id) or "no resolution"
    if leader is None:
        now = "superseded, with no decision in its place"
    else:
        now = _resolution_name(db, leader.resolution_id) or "recorded without a resolution yet"
    note = f"Overridden by hand against the {leader_name} decision ({old}); that decision is now {now}."
    row = derivation(db, leader.resolution_id if leader else None, follower.item_id)
    if row is not None and row.action == "derive":
        note += f" It would derive {_resolution_name(db, row.dependent_resolution_id)}."
    elif row is not None and row.action == "not_derived":
        note += f" It does not settle this item: {row.reason}"
    return note + " Review the override: save this decision to keep it, or supersede it to take what the new decision gives."


def _review_override(db: Session, follower: models.EngagementDecision, leader_item_id: str,
                     leader: models.EngagementDecision | None, target: str | None, now: datetime.datetime) -> bool:
    """A manual decision on a dependent. Returns whether it changed."""
    if follower.overrides_derivation:
        stands = (leader is not None and leader.id == follower.derived_from_decision_id
                  and leader.resolution_id == follower.derived_against_resolution_id)
        note = None if stands else review_note(db, follower, leader_item_id, leader)
        if follower.needs_review == (not stands) and follower.review_note == note:
            return False
        follower.needs_review = not stands
        follower.review_note = note
        follower.updated_at = now
        return True
    if target is not None:
        # Decided by hand before the derivation applied: kept, and linked
        # as overriding it.
        follower.derived_from_decision_id = leader.id
        follower.derived_against_resolution_id = leader.resolution_id
        follower.overrides_derivation = True
        follower.updated_at = now
        return True
    return False


def rederive(db: Session, engagement_id: str, leader_item_id: str) -> list[models.EngagementDecision]:
    """Brings every dependent of `leader_item_id` in step with the leader's
    live decision. Creates, updates or supersedes derived decisions; links
    and reviews (never changes the choice of) manual ones. Flushes; the
    caller commits."""
    now = datetime.datetime.now(datetime.timezone.utc)
    leader = live_decision(db, engagement_id, leader_item_id)
    leader_item = db.get(models.CatalogItem, leader_item_id)
    changed = []
    for dependent_item_id in dependents_of(db, leader_item_id):
        dependent_item = db.get(models.CatalogItem, dependent_item_id)
        if dependent_item is None or dependent_item.deleted_at is not None:
            continue
        follower = live_decision(db, engagement_id, dependent_item_id)
        target = target_for(db, engagement_id, leader, dependent_item_id)

        if follower is not None and follower.source == "manual":
            if _review_override(db, follower, leader_item_id, leader, target, now):
                changed.append(follower)
            continue

        if target is None:
            # The leader settles nothing here (no decision, not_derived, no
            # internal client): a derived decision no longer stands.
            if follower is not None:
                follower.status = "superseded"
                follower.updated_at = now
                changed.append(follower)
            continue

        if follower is None:
            follower = models.EngagementDecision(id=uuid.uuid4(), engagement_id=engagement_id, item_id=dependent_item_id,
                                                 source="derived", created_at=now)
            db.add(follower)
        row = derivation(db, leader.resolution_id, dependent_item_id)
        follower.derived_from_decision_id = leader.id
        follower.derived_against_resolution_id = leader.resolution_id
        follower.resolution_id = target
        follower.candidates_considered = _live_resolution_ids(db, dependent_item_id)
        follower.status = leader.status
        follower.rationale = (
            f"Derived from the {leader_item.name if leader_item else leader_item_id} decision "
            f"({_resolution_name(db, leader.resolution_id)}). {row.reason}"
        )
        follower.forcing_perspective = leader.forcing_perspective
        follower.forcing_rationale = leader.forcing_rationale
        follower.approver_name = leader.approver_name if leader.status == "approved" else None
        follower.approver_role = leader.approver_role if leader.status == "approved" else None
        follower.decision_date = leader.decision_date if leader.status == "approved" else None
        follower.overrides_derivation = False
        follower.needs_review = False
        follower.review_note = None
        follower.updated_at = now
        changed.append(follower)
    db.flush()
    return changed


def rederive_leaders_of(db: Session, engagement_id: str, dependent_item_id: str) -> None:
    """After a dependent's own decision changes (superseded, say), its leaders
    re-derive it: superseding an override takes the derived decision again."""
    for leader_item_id in leaders_of(db, dependent_item_id):
        rederive(db, engagement_id, leader_item_id)


def rebaseline_override(db: Session, decision: models.EngagementDecision) -> None:
    """A person wrote this manual decision: it now stands against the
    current leading decision, so any review flag is answered."""
    decision.needs_review = False
    decision.review_note = None
    if decision.derived_from_decision_id is None:
        return
    previous = db.get(models.EngagementDecision, decision.derived_from_decision_id)
    if previous is None:
        return
    leader = live_decision(db, decision.engagement_id, previous.item_id)
    if leader is not None:
        decision.derived_from_decision_id = leader.id
        decision.derived_against_resolution_id = leader.resolution_id


def subsumptions(db: Session, engagement_id: str, project_items: set[str]) -> dict[str, dict]:
    """For one project's found items: dependent -> {action, item_id,
    decision_id, resolution_id, resolution_name, reason}, where a leader is
    found on the same project and its live decision's resolution declares
    subsume or not_subsumed for the dependent."""
    result = {}
    for leader_item_id in sorted(project_items):
        dependents = [d for d in dependents_of(db, leader_item_id, SUBSUMPTION_ACTIONS) if d in project_items]
        if not dependents:
            continue
        leader = live_decision(db, engagement_id, leader_item_id)
        for dependent_item_id in dependents:
            row = derivation(db, leader.resolution_id if leader else None, dependent_item_id)
            if row is None or row.action not in SUBSUMPTION_ACTIONS:
                continue
            result[dependent_item_id] = {
                "action": row.action, "item_id": leader_item_id, "decision_id": str(leader.id),
                "resolution_id": leader.resolution_id, "resolution_name": _resolution_name(db, leader.resolution_id),
                "reason": row.reason,
            }
    return result
