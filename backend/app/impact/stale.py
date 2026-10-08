"""Part C, "When the decision changes": impact computed for one decision is
stale once the live decision differs, naming the resolution, until the next
scan recomputes it. Stale impact is shown as stale, never as current.

Engagement-wide and idempotent, so every path that changes decisions —
a person's write, a supersede, a derived follower re-derived (Part U) —
calls the one function after its writes, and a decision changed back clears
the flag again.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models


def _live_choices(db: Session, engagement_id: str) -> dict[str, str]:
    """item → chosen resolution, for live decisions that have chosen one —
    the same reading impact-analysis makes (ImpactDatabase.GetDecisionsAsync)."""
    rows = db.execute(
        select(models.EngagementDecision.item_id, models.EngagementDecision.resolution_id).where(
            models.EngagementDecision.engagement_id == engagement_id,
            models.EngagementDecision.status != "superseded",
            models.EngagementDecision.resolution_id.is_not(None),
        )
    ).all()
    return {item_id: resolution_id for item_id, resolution_id in rows}


def _name(db: Session, resolution_id: str) -> str:
    resolution = db.get(models.ItemResolution, resolution_id)
    return resolution.name if resolution is not None else resolution_id


def reason(db: Session, computed_for: str | None, now: str | None) -> str:
    if now is None:
        return (f"Computed for the decision on {_name(db, computed_for)}, which has since been withdrawn. "
                "The default is now effective; recomputed on the next scan.")
    if computed_for is None:
        return f"Computed with no decision. {_name(db, now)} has since been chosen; recomputed on the next scan."
    return (f"Computed for {_name(db, computed_for)}. The decision has since changed to {_name(db, now)}; "
            "recomputed on the next scan.")


def refresh(db: Session, engagement_id: str) -> int:
    """Marks or clears `impact_summaries.stale` for the engagement against its
    live decisions. Flushes; the caller commits. Returns the number stale."""
    choices = _live_choices(db, engagement_id)
    stale = 0
    summaries = db.scalars(select(models.ImpactSummary).where(models.ImpactSummary.engagement_id == engagement_id)).all()
    for summary in summaries:
        now = choices.get(summary.item_id)
        if now == summary.decision_resolution_id:
            summary.stale, summary.stale_reason = False, None
        else:
            summary.stale, summary.stale_reason = True, reason(db, summary.decision_resolution_id, now)
            stale += 1
    db.flush()
    return stale
