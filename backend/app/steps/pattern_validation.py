"""Step 6 — pattern validation. 27-STEP-006-PATTERN-VALIDATION.md Part D.

A human decides what each candidate cluster is. This step raises the
questions, then — on a later resume — applies the answers.

**The step applies decisions; the UI does not write them.** The queue
records the human's answer and this step is what acts on it. That keeps
every cluster mutation auditable to a specific job execution, and means a
decision made while no execution is running is picked up on the next
resume rather than lost.
"""

import datetime
import hashlib
import json
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.db import SessionLocal
from app.workflow.contract import StepContext, StepOutput, StepResult

STEP_NAME = "pattern-validation"
ITEM_TYPE = "pattern_candidate"
ARTIFACT_TYPE = "pattern-validation-decisions"
ARTIFACT_VERSION = "1.0.0"

# Outcomes, Part C. `defer` is handled by its own endpoint and never lands
# in `outcome` — deferring is a decision about *when* to decide, not what.
_CLUSTER_STATUS_FOR_OUTCOME = {
    "create_pattern": "validated_new",
    "merge_into_pattern": "merged",
    "reject": "rejected",
}


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _title(cluster: models.PatternCandidateCluster) -> str:
    if cluster.suggested_name:
        return cluster.suggested_name
    signals = (cluster.canonical_signature or {}).get("signals") or []
    if signals:
        return f"Unnamed shape — {', '.join(signals[:3])}{'…' if len(signals) > 3 else ''}"
    return f"Unnamed shape — {cluster.cluster_id}"


def _payload(
    db: Session,
    cluster: models.PatternCandidateCluster,
    coverage: dict,
    is_rereview: bool,
    previous_decision: dict | None,
) -> dict:
    members = db.execute(
        select(models.Project.relative_path, models.Repository.name)
        .join(models.PatternCandidateMember, models.PatternCandidateMember.project_id == models.Project.id)
        .join(models.Repository, models.Repository.id == models.PatternCandidateMember.repository_id)
        .where(models.PatternCandidateMember.cluster_id == cluster.cluster_id)
        .order_by(models.Repository.name, models.Project.relative_path)
        .limit(5)
    ).all()

    return {
        "cluster_id": cluster.cluster_id,
        "cluster_method": cluster.cluster_method,
        "member_count": cluster.member_count,
        "repository_count": cluster.repository_count,
        "repository_distribution": cluster.repository_distribution,
        "cohesion": float(cluster.cohesion) if cluster.cohesion is not None else None,
        "is_singleton": cluster.is_singleton,
        "canonical_signature": cluster.canonical_signature,
        # Shown here, unlike to the narrator: a human deciding whether to
        # merge needs it, whereas a model naming a shape would be biased by
        # it (Part B, and 26's Part E).
        "similar_patterns": cluster.similar_patterns or [],
        "suggested_name": cluster.suggested_name,
        "suggested_description": cluster.suggested_description,
        "naming_source": cluster.naming_source,
        "sample_members": [{"project_path": path, "repository_slug": repo} for path, repo in members],
        # What makes a decision on a partial estate defensible. A reviewer
        # seeing a two-member cluster at 24% coverage should treat it
        # differently from the same cluster at 90%.
        "coverage_at_raise": coverage,
        "is_rereview": is_rereview,
        "previous_decision": previous_decision,
    }


def _coverage(db: Session, engagement_id: str) -> dict:
    run = db.scalars(
        select(models.PatternDiscoveryRun)
        .where(models.PatternDiscoveryRun.engagement_id == engagement_id)
        .order_by(models.PatternDiscoveryRun.run_at.desc())
        .limit(1)
    ).first()
    if run is None:
        return {"repositories_included": 0, "repositories_pending": 0, "coverage_ratio": None}
    included = db.scalars(
        select(models.Repository.id)
        .where(models.Repository.engagement_id == engagement_id)
        .where(models.Repository.deleted_at.is_(None))
    ).all()
    ratio = float(run.coverage_ratio) if run.coverage_ratio is not None else None
    covered = round(ratio * len(included)) if ratio is not None else 0
    return {
        "repositories_included": covered,
        "repositories_pending": len(included) - covered,
        "coverage_ratio": ratio,
    }


def _deferral_met(item: models.ValidationQueueItem, cluster: models.PatternCandidateCluster, coverage: dict) -> bool:
    """Either threshold alone resurfaces the item — they are alternatives,
    not a conjunction. A reviewer who says "ask me at 60% coverage" and one
    who says "ask me at 10 members" are both satisfied by whichever happens
    first."""
    if item.deferred_until_member_count is not None and cluster.member_count >= item.deferred_until_member_count:
        return True
    ratio = coverage.get("coverage_ratio")
    if (
        item.deferred_until_coverage is not None
        and ratio is not None
        and ratio >= float(item.deferred_until_coverage)
    ):
        return True
    return False


def _previous_decision(item: models.ValidationQueueItem) -> dict:
    return {
        "outcome": item.outcome,
        "decision_note": item.decision_note,
        "decided_by": item.decided_by,
        "decided_at": item.decided_at.isoformat() if item.decided_at else None,
        "member_count_then": (item.payload or {}).get("member_count"),
        "coverage_then": ((item.payload or {}).get("coverage_at_raise") or {}).get("coverage_ratio"),
    }


def _apply_decisions(db: Session, engagement_id: str, coverage: dict) -> list[dict]:
    """Step 4 of Part D's execution logic: apply decided outcomes to
    `pattern_candidate_clusters`, recording the evidence the decision was
    made on."""
    applied = []
    decided = db.scalars(
        select(models.ValidationQueueItem)
        .where(models.ValidationQueueItem.engagement_id == engagement_id)
        .where(models.ValidationQueueItem.step_name == STEP_NAME)
        .where(models.ValidationQueueItem.status == "decided")
        .order_by(models.ValidationQueueItem.item_key)
    ).all()

    for item in decided:
        cluster = db.get(models.PatternCandidateCluster, item.item_key)
        if cluster is None:
            continue
        new_status = _CLUSTER_STATUS_FOR_OUTCOME.get(item.outcome)
        if new_status is None:
            continue

        detail = item.outcome_detail or {}
        resolved_pattern_id = detail.get("pattern_id")

        cluster.status = new_status
        cluster.resolution_note = item.decision_note
        if resolved_pattern_id and db.get(models.Pattern, resolved_pattern_id) is not None:
            cluster.resolved_pattern_id = resolved_pattern_id
        # Decision context (26's Part D): what the human could see at the
        # time. The re-review trigger measures growth from here, so it must
        # be the evidence at decision, never the evidence now.
        if cluster.decided_at_member_count is None or item.decided_at is not None:
            cluster.decided_at_member_count = (item.payload or {}).get("member_count", cluster.member_count)
            raised_coverage = ((item.payload or {}).get("coverage_at_raise") or {}).get("coverage_ratio")
            cluster.decided_at_coverage = raised_coverage if raised_coverage is not None else coverage.get("coverage_ratio")
        # The question has been answered; a later growth spurt re-raises it
        # through the re-review path rather than leaving this flag set.
        cluster.needs_rereview = False
        cluster.rereview_reason = None

        applied.append(
            {
                "cluster_id": cluster.cluster_id,
                "outcome": item.outcome,
                "resolved_pattern_id": cluster.resolved_pattern_id,
                "decision_note": item.decision_note,
                "decided_by": item.decided_by,
                "decided_at": item.decided_at.isoformat() if item.decided_at else None,
                "decided_at_coverage": float(cluster.decided_at_coverage) if cluster.decided_at_coverage is not None else None,
                "decided_at_member_count": cluster.decided_at_member_count,
                "is_rereview": bool((item.payload or {}).get("is_rereview")),
            }
        )
    return applied


def _serialise(artifact: dict) -> bytes:
    return (json.dumps(artifact, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def run(context: StepContext, session: Session | None = None) -> StepResult:
    """Declaring `session` is what makes the python adapter hand over the
    **engine's own** session.

    This step writes validation_queue rows that foreign-key
    `wf_job_executions` and `wf_step_executions` — rows the engine has
    flushed but not committed. From a separate session those do not exist
    yet and the insert fails on the foreign key. Joining the engine's
    transaction is also the correct semantics: if a later step in the job
    fails, the questions this step raised roll back with it rather than
    stranding a queue that refers to an execution nobody can see.

    The corollary is that this step must never commit. The engine owns the
    transaction boundary; committing here would publish a partially-run
    execution.
    """
    if session is not None:
        return _run(session, context)
    # Standalone invocation (a test, or a future non-engine caller) still
    # works, on its own session and its own transaction.
    db: Session = SessionLocal()
    try:
        result = _run(db, context)
        db.commit()
        return result
    finally:
        db.close()


def _run(db: Session, context: StepContext) -> StepResult:
    engagement_id = context.parameters["engagement_id"]
    coverage = _coverage(db, engagement_id)

    # 1. Both inputs are optional, so "no clusters" is an ordinary outcome
    #    rather than a failure. With step 5 stubbed or disabled by policy
    #    the artifact never resolves and the step is simply invoked without
    #    it — see the optional-input handling in the executor.
    clusters = db.scalars(
        select(models.PatternCandidateCluster)
        .where(models.PatternCandidateCluster.engagement_id == engagement_id)
        .order_by(models.PatternCandidateCluster.cluster_id)
    ).all()
    if not clusters:
        return StepResult(
            exit_status="NOOP",
            exit_message=(
                f"No candidate clusters for '{engagement_id}'. Step 5 has not produced any — "
                f"it may be stubbed, disabled by policy, or the estate may be fully classified."
            ),
        )

    items = db.scalars(
        select(models.ValidationQueueItem)
        .where(models.ValidationQueueItem.engagement_id == engagement_id)
        .where(models.ValidationQueueItem.step_name == STEP_NAME)
    ).all()
    open_by_key = {i.item_key: i for i in items if i.status == "open"}
    decided_by_key: dict[str, models.ValidationQueueItem] = {}
    for item in items:
        if item.status != "decided":
            continue
        current = decided_by_key.get(item.item_key)
        if current is None or (item.decided_at and current.decided_at and item.decided_at > current.decided_at):
            decided_by_key[item.item_key] = item

    raised = superseded = reopened = withdrawn = 0

    for cluster in clusters:
        existing = open_by_key.get(cluster.cluster_id)

        # 3. Withdraw open items whose subject has gone. A stale cluster is
        #    retained for its history (26 Part D) but there is nothing left
        #    to decide about it, and leaving the item open would block the
        #    gate on a question with no subject.
        if cluster.is_stale or cluster.member_count == 0:
            if existing is not None:
                existing.status = "withdrawn"
                existing.decision_note = "Cluster members all disappeared; nothing left to decide."
                withdrawn += 1
            continue

        if existing is not None:
            # 2a. An open item already asks this question. Reopen it if a
            #     deferral threshold has since been met.
            if existing.is_deferred and _deferral_met(existing, cluster, coverage):
                existing.deferred_at = None
                existing.deferred_until_coverage = None
                existing.deferred_until_member_count = None
                existing.payload = {**(existing.payload or {}), "member_count": cluster.member_count,
                                    "coverage_at_raise": coverage}
                reopened += 1
            continue

        prior = decided_by_key.get(cluster.cluster_id)
        if prior is not None:
            # 2b. Decided, and the subject has not changed materially —
            #     leave it answered. `needs_rereview` is step 5's judgement
            #     that the evidence has grown enough to be worth re-asking.
            if not cluster.needs_rereview:
                continue
            # 2c. Decided, but materially changed. Supersede rather than
            #     reopen, so the original answer and the evidence it was
            #     given on stay on the record — that trail is the whole
            #     point of asking again.
            prior.status = "superseded"
            superseded += 1
            db.add(
                models.ValidationQueueItem(
                    engagement_id=engagement_id,
                    job_execution_id=uuid.UUID(context.job_execution_id),
                    step_execution_id=uuid.UUID(context.step_execution_id),
                    step_name=STEP_NAME,
                    item_type=ITEM_TYPE,
                    item_key=cluster.cluster_id,
                    title=_title(cluster),
                    payload=_payload(db, cluster, coverage, True, _previous_decision(prior)),
                    priority=40 if not cluster.is_singleton else 60,
                )
            )
            raised += 1
            continue

        # 2d. No item at all — raise one. Singletons sort lower: they are
        #     not patterns yet and should not crowd out a shape recurring
        #     across five repositories.
        if cluster.status != "candidate":
            continue
        db.add(
            models.ValidationQueueItem(
                engagement_id=engagement_id,
                job_execution_id=uuid.UUID(context.job_execution_id),
                step_execution_id=uuid.UUID(context.step_execution_id),
                step_name=STEP_NAME,
                item_type=ITEM_TYPE,
                item_key=cluster.cluster_id,
                title=_title(cluster),
                payload=_payload(db, cluster, coverage, False, None),
                priority=60 if cluster.is_singleton else 50,
            )
        )
        raised += 1

    db.flush()

    # 4. Apply what humans have decided since the last run.
    applied = _apply_decisions(db, engagement_id, coverage)

    # 5. Emit the audit record. Decision timestamps and reviewer names are
    #    content here, not volatile fields — the artifact is *about* them —
    #    so two runs with no new decisions produce identical checksums.
    artifact = {
        "artifact_type": ARTIFACT_TYPE,
        "artifact_version": ARTIFACT_VERSION,
        "engagement_id": engagement_id,
        "decisions": sorted(applied, key=lambda d: d["cluster_id"]),
        "decision_count": len(applied),
    }
    body = _serialise(artifact)
    output_dir = Path(context.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / "pattern-validation-decisions.json"
    artifact_path.write_bytes(body)

    # 6. Anything still awaiting a human blocks the gate.
    still_open = db.scalars(
        select(models.ValidationQueueItem)
        .where(models.ValidationQueueItem.engagement_id == engagement_id)
        .where(models.ValidationQueueItem.step_name == STEP_NAME)
        .where(models.ValidationQueueItem.status == "open")
    ).all()
    # A deferred item is open but does NOT block. Deferring is itself a
    # decision — "ask me again when the evidence improves" — and the
    # resurfacing machinery brings it back. Were it to block, one thin
    # cluster at 24% coverage would hold the estate's consolidation job open
    # indefinitely, which is precisely the premature-reject pressure that
    # `defer` exists to remove.
    blocking = [i for i in still_open if not i.is_deferred]
    deferred = len(still_open) - len(blocking)

    # No commit: see run()'s docstring. Flush so the counts above reflect
    # this run's inserts, and leave the boundary to the engine.
    db.flush()

    outputs = [
        StepOutput(
            artifact_type=ARTIFACT_TYPE,
            artifact_version=ARTIFACT_VERSION,
            uri=f"file:///{artifact_path.as_posix()}",
            checksum="sha256:" + hashlib.sha256(body).hexdigest(),
            metadata={"decision_count": len(applied), "open_item_count": len(blocking)},
        )
    ]
    activity = (
        f"raised {raised}, superseded {superseded}, reopened {reopened}, withdrawn {withdrawn}, "
        f"applied {len(applied)} decision(s)"
    )

    if blocking:
        return StepResult(
            exit_status="AWAITING_APPROVAL",
            exit_message=(
                f"{len(blocking)} item(s) awaiting a decision for '{engagement_id}'"
                + (f", {deferred} deferred" if deferred else "")
                + f". {activity}."
            ),
            outputs=outputs,
            metrics={"read_count": len(clusters), "write_count": raised + len(applied), "commit_count": 1},
        )

    return StepResult(
        exit_status="COMPLETED",
        exit_message=(
            f"All candidate clusters for '{engagement_id}' are resolved"
            + (f" ({deferred} deferred to a later run)" if deferred else "")
            + f". {activity}."
        ),
        outputs=outputs,
        metrics={"read_count": len(clusters), "write_count": raised + len(applied), "commit_count": 1},
    )
