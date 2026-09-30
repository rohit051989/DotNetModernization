"""Pattern candidate clusters — step 5's output, and the review surface
step 6 will act on. See 26-STEP-005-PATTERN-DISCOVERY.md.

Read-only apart from `retry-narration`. The decision actions (validate,
merge, reject) belong to step 6 and are not here yet.
"""

import json
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.db import get_db
from app.errors import ErrorResponse, error

router = APIRouter(prefix="/api/engagements", tags=["Pattern Candidates"])

_NOT_FOUND = {"model": ErrorResponse, "description": "No engagement exists with this id."}

# Mirrors the step registration's adapter_config command. Kept here rather
# than read from wf_step_registrations because retry is an operator action
# outside the workflow engine: it re-runs one side effect of a step, not
# the step, and must not create a step execution that never clustered.
_STEP_DIR = Path(__file__).resolve().parents[3] / "steps" / "step-005-pattern-discovery"
_STEP_PYTHON = _STEP_DIR / ".venv" / "Scripts" / "python.exe"


class ClusterMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    project_path: str = Field(description="Repository-relative path to the project file.")
    repository_name: str
    classification_status: str = Field(description="Why step 4 left this project unclassified — NO_PATTERN_MATCHED or AMBIGUOUS.")
    similarity_to_signature: float | None = Field(description="Jaccard between this project's signals and the cluster's shared shape. 1.0 in an exact cluster.")
    signal_count: int


class PatternCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cluster_id: str = Field(description="Deterministic hash of the shape. Stable across runs, which is what lets a step 6 decision persist.")
    cluster_method: str = Field(description="'exact' — one identical shape — or 'similarity', several merged.")
    canonical_signature: dict = Field(description="The shape: facets plus the signal names every member shares.")
    signal_count: int
    member_count: int
    repository_count: int
    repository_distribution: dict = Field(description="Members per repository. A cluster spanning many repositories is a stronger candidate than one concentrated in a single repository.")
    cohesion: float | None = Field(description="Minimum pairwise Jaccard among members. Below the similarity threshold means the cluster is chained, not tight.")
    is_singleton: bool
    is_stale: bool = Field(description="Every member has disappeared. Retained rather than deleted, because the step 6 decision attached to it is history.")
    similar_patterns: list | None = Field(description="Active catalog patterns this shape resembles, for step 6's 'merge into existing' action.")
    status: str
    resolved_pattern_id: str | None
    resolution_note: str | None
    needs_rereview: bool = Field(description="The evidence has grown materially since this cluster was decided. Not a reversal — the information changed, not the decision.")
    rereview_reason: str | None
    # Advisory naming (Part E). Null throughout when narration was
    # unavailable or disabled, which is what the run-level narration_status
    # explains.
    suggested_name: str | None
    suggested_description: str | None
    suggested_pattern_id: str | None
    narration_confidence: str | None
    naming_source: str = Field(description="'claude-code', 'human' once someone renames it at step 6, or 'none'.")
    members: list[ClusterMemberOut]


class NarrationStatusOut(BaseModel):
    status: str = Field(description="succeeded | partial | failed | disabled.")
    reason: str | None = Field(description="Why, in words. Null only when status is 'succeeded'.")
    narrated_cluster_count: int
    cluster_count: int
    run_at: str | None
    retryable: bool = Field(description="True unless narration already succeeded — the UI's cue to offer the retry action.")


class PatternCandidatesOut(BaseModel):
    engagement_id: str
    coverage_ratio: float | None = Field(description="Share of in-scope repositories that had classification results when clustering last ran.")
    partial_estate: bool = Field(description="True when some in-scope repository has no classification results. The expected state at fleet scale, not a warning.")
    narration: NarrationStatusOut | None = Field(description="Null when step 5 has never run for this engagement.")
    clusters: list[PatternCandidateOut]


class RetryNarrationResult(BaseModel):
    narration_status: str
    narration_reason: str | None
    narrated_count: int
    cluster_count: int


def _require_engagement(db: Session, engagement_id: str) -> None:
    if db.get(models.Engagement, engagement_id) is None:
        raise error(404, f"No engagement '{engagement_id}'", code="NOT_FOUND")


@router.get(
    "/{engagement_id}/pattern-candidates",
    response_model=PatternCandidatesOut,
    summary="Candidate patterns discovered by step 5",
    response_description="Every non-stale cluster, with its members and its advisory name, plus the run-level narration status.",
    operation_id="list_pattern_candidates",
    responses={404: _NOT_FOUND},
)
def list_pattern_candidates(engagement_id: str, db: Session = Depends(get_db)):
    """
    The narration status is returned whether or not any cluster is named.
    That is the point of it: unnamed clusters with no explanation read as
    "the platform has nothing to say about this shape", when the truth may
    be that the narrator could not be reached — a completely different
    thing to act on.
    """
    _require_engagement(db, engagement_id)

    clusters = db.scalars(
        select(models.PatternCandidateCluster)
        .where(models.PatternCandidateCluster.engagement_id == engagement_id)
        # Stale clusters are retained for their history but are not review
        # queue items — every member has disappeared.
        .where(models.PatternCandidateCluster.is_stale.is_(False))
        .order_by(
            models.PatternCandidateCluster.member_count.desc(),
            models.PatternCandidateCluster.cluster_id,
        )
    ).all()

    members_by_cluster: dict[str, list[ClusterMemberOut]] = {}
    if clusters:
        rows = db.execute(
            select(
                models.PatternCandidateMember.cluster_id,
                models.PatternCandidateMember.project_id,
                models.PatternCandidateMember.classification_status,
                models.PatternCandidateMember.similarity_to_signature,
                models.PatternCandidateMember.signal_count,
                models.Project.relative_path,
                models.Repository.name,
            )
            .join(models.Project, models.Project.id == models.PatternCandidateMember.project_id)
            .join(models.Repository, models.Repository.id == models.PatternCandidateMember.repository_id)
            .where(models.PatternCandidateMember.cluster_id.in_([c.cluster_id for c in clusters]))
            .order_by(models.Repository.name, models.Project.relative_path)
        ).all()
        for row in rows:
            members_by_cluster.setdefault(row[0], []).append(
                ClusterMemberOut(
                    project_id=row[1],
                    classification_status=row[2],
                    similarity_to_signature=float(row[3]) if row[3] is not None else None,
                    signal_count=row[4],
                    project_path=row[5],
                    repository_name=row[6],
                )
            )

    run = db.scalars(
        select(models.PatternDiscoveryRun)
        .where(models.PatternDiscoveryRun.engagement_id == engagement_id)
        .order_by(models.PatternDiscoveryRun.run_at.desc())
        .limit(1)
    ).first()

    return PatternCandidatesOut(
        engagement_id=engagement_id,
        coverage_ratio=float(run.coverage_ratio) if run and run.coverage_ratio is not None else None,
        partial_estate=bool(run.partial_estate) if run else False,
        narration=(
            NarrationStatusOut(
                status=run.narration_status,
                reason=run.narration_reason,
                narrated_cluster_count=run.narrated_cluster_count,
                cluster_count=run.cluster_count,
                run_at=run.run_at.isoformat(),
                retryable=run.narration_status != "succeeded",
            )
            if run
            else None
        ),
        clusters=[
            PatternCandidateOut(
                cluster_id=c.cluster_id,
                cluster_method=c.cluster_method,
                canonical_signature=c.canonical_signature,
                signal_count=c.signal_count,
                member_count=c.member_count,
                repository_count=c.repository_count,
                repository_distribution=c.repository_distribution,
                cohesion=float(c.cohesion) if c.cohesion is not None else None,
                is_singleton=c.is_singleton,
                is_stale=c.is_stale,
                similar_patterns=c.similar_patterns,
                status=c.status,
                resolved_pattern_id=c.resolved_pattern_id,
                resolution_note=c.resolution_note,
                needs_rereview=c.needs_rereview,
                rereview_reason=c.rereview_reason,
                suggested_name=c.suggested_name,
                suggested_description=c.suggested_description,
                suggested_pattern_id=c.suggested_pattern_id,
                narration_confidence=c.narration_confidence,
                naming_source=c.naming_source,
                members=members_by_cluster.get(c.cluster_id, []),
            )
            for c in clusters
        ],
    )


@router.post(
    "/{engagement_id}/pattern-candidates/retry-narration",
    response_model=RetryNarrationResult,
    summary="Re-run narration against the existing clusters",
    response_description="The new narration status.",
    operation_id="retry_pattern_candidate_narration",
    responses={
        404: _NOT_FOUND,
        409: {"model": ErrorResponse, "description": "Step 5 has not run for this engagement, so there are no clusters to narrate."},
        500: {"model": ErrorResponse, "description": "The step 5 process could not be invoked."},
    },
)
def retry_narration(engagement_id: str, db: Session = Depends(get_db)):
    """
    Re-runs **narration only**, against the clusters already stored. It
    does not re-cluster, and it cannot change the
    `pattern-candidate-clusters` artifact or its checksum — narration is
    not an input to it (Part A2). That independence is exactly what makes
    this action safe to offer as a button.

    Re-clustering instead would be actively wrong: the estate may have
    been rescanned since, so it could produce a different clustering and
    silently renumber shapes a human is mid-review on. To re-cluster,
    launch `phase0-estate-consolidation`.

    Runs synchronously — narration of a whole engagement is one CLI call,
    and the operator is waiting for the answer.
    """
    _require_engagement(db, engagement_id)

    exists = db.scalars(
        select(models.PatternCandidateCluster.cluster_id)
        .where(models.PatternCandidateCluster.engagement_id == engagement_id)
        .limit(1)
    ).first()
    if exists is None:
        raise error(
            409,
            f"No clusters recorded for '{engagement_id}'. Run phase0-estate-consolidation first.",
            code="NO_CLUSTERS",
        )

    if not _STEP_PYTHON.exists():
        raise error(500, f"Step 5 interpreter not found at {_STEP_PYTHON}", code="STEP_UNAVAILABLE")

    try:
        completed = subprocess.run(
            [
                str(_STEP_PYTHON),
                "main.py",
                "--retry-narration",
                engagement_id,
                "--database-url",
                settings.database_url,
            ],
            capture_output=True,
            text=True,
            cwd=str(_STEP_DIR),
            timeout=900,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise error(500, f"Could not run narration: {type(exc).__name__}: {exc}", code="STEP_UNAVAILABLE") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        raise error(500, f"Narration retry failed: {detail[-1] if detail else 'no output'}", code="STEP_FAILED")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise error(500, "Narration retry produced no parseable result", code="STEP_FAILED") from exc

    return RetryNarrationResult(**payload)


# --------------------------------------------------------------------------
# Step 6 actions — 27-STEP-006-PATTERN-VALIDATION.md Part C and Part E.
#
# Both are READ-ONLY proposals. Neither persists a pattern and neither edits
# one. They exist to put a well-formed starting point in front of a human,
# not to make catalog changes as a side effect of a queue action.
# --------------------------------------------------------------------------


class DraftRuleCondition(BaseModel):
    id: str
    signal: dict | None = None
    field: str | None = None
    equals: str | None = None
    weight: int | None = None


class DraftPatternOut(BaseModel):
    """A pattern the rule builder can open. **Not persisted.**"""

    cluster_id: str
    is_draft: bool = Field(description="Always true. Nothing here has been written to the catalog.")
    pattern: dict = Field(description="The pre-populated pattern, with rules_status 'draft'.")
    anchor_ranking: list[dict] = Field(description="Candidate anchors with the prevalence that ranked them — a signal on 90% of projects is a poor anchor.")
    notes: list[str] = Field(description="What the human should check before promoting this draft.")


class MergeProposalOut(BaseModel):
    """A suggested rule amendment. **The target pattern is not modified.**"""

    cluster_id: str
    pattern_id: str
    applied: bool = Field(description="Always false. Widening a master-catalog pattern is its own reviewed edit.")
    signals_missing_from_pattern: list[str] = Field(description="Present across the cluster, absent from the pattern's rules — the substance of the diff.")
    signals_already_covered: list[str]
    proposed_additions: list[dict] = Field(description="Ready-to-paste `supporting` conditions for the rule builder.")
    impact: dict = Field(description="What applying this would affect, so the reviewer can weigh it.")
    notes: list[str]


def _signal_prevalence(db: Session, engagement_id: str) -> dict[str, int]:
    """How many projects in the engagement carry each signal. Used to rank
    anchors: a signal on nearly every project identifies nothing."""
    rows = db.execute(
        select(models.FingerprintSignal.signal_name, func.count(func.distinct(models.FingerprintSignal.project_id)))
        .join(models.Project, models.Project.id == models.FingerprintSignal.project_id)
        .join(models.Repository, models.Repository.id == models.Project.repository_id)
        .where(models.Repository.engagement_id == engagement_id)
        .where(models.Repository.deleted_at.is_(None))
        .group_by(models.FingerprintSignal.signal_name)
    ).all()
    return {name: n for name, n in rows}


def _member_signal_counts(db: Session, cluster_id: str) -> tuple[dict[str, int], int]:
    """Per-signal member counts within the cluster, and the member total.
    Drives the all/supporting split: universal signals define the shape,
    partial ones support it."""
    rows = db.execute(
        select(models.FingerprintSignal.signal_name, func.count(func.distinct(models.FingerprintSignal.project_id)))
        .join(models.PatternCandidateMember, models.PatternCandidateMember.project_id == models.FingerprintSignal.project_id)
        .where(models.PatternCandidateMember.cluster_id == cluster_id)
        .group_by(models.FingerprintSignal.signal_name)
    ).all()
    total = db.scalar(
        select(func.count()).select_from(models.PatternCandidateMember).where(models.PatternCandidateMember.cluster_id == cluster_id)
    ) or 0
    return {name: n for name, n in rows}, total


def _require_cluster(db: Session, engagement_id: str, cluster_id: str) -> models.PatternCandidateCluster:
    _require_engagement(db, engagement_id)
    cluster = db.get(models.PatternCandidateCluster, cluster_id)
    if cluster is None or cluster.engagement_id != engagement_id:
        raise error(404, f"No cluster '{cluster_id}' in engagement '{engagement_id}'", code="NOT_FOUND")
    return cluster


_FACET_TO_METADATA_FIELD = {
    "project_role": None,  # role is eligibility, not a metadata condition
    "framework_family": "frameworkFamily",
    "output_type": "outputType",
    "structural_type": "structuralType",
}


@router.post(
    "/{engagement_id}/pattern-candidates/{cluster_id}/create-pattern",
    response_model=DraftPatternOut,
    summary="Pre-populate a draft pattern from a cluster",
    response_description="A draft for the rule builder. Nothing is persisted.",
    operation_id="create_pattern_draft",
    responses={404: {"model": ErrorResponse, "description": "No such engagement or cluster."}},
)
def create_pattern_draft(engagement_id: str, cluster_id: str, db: Session = Depends(get_db)):
    """
    Returns a **draft**, never a persisted pattern.

    A pattern is master-catalog, client-agnostic IP shared by every
    engagement. Writing one as a side effect of clearing a queue item would
    put a machine-generated rule into that shared catalog with no review.
    So this endpoint builds the starting point and hands it to the rule
    builder; creating the pattern is a separate, deliberate act through
    `POST /api/patterns`, and `rules_status` is `draft` even then.
    """
    cluster = _require_cluster(db, engagement_id, cluster_id)

    signature = cluster.canonical_signature or {}
    signals = list(signature.get("signals") or [])
    facets = signature.get("facets") or {}

    prevalence = _signal_prevalence(db, engagement_id)
    project_total = db.scalar(
        select(func.count(func.distinct(models.Project.id)))
        .join(models.Repository, models.Repository.id == models.Project.repository_id)
        .where(models.Repository.engagement_id == engagement_id)
        .where(models.Repository.deleted_at.is_(None))
    ) or 1
    member_counts, member_total = _member_signal_counts(db, cluster_id)

    # Anchors ranked by rarity across the engagement (Part C). A signal on
    # 90% of projects is a poor anchor however central it feels.
    ranking = sorted(
        (
            {
                "signal_name": s,
                "projects_with_signal": prevalence.get(s, 0),
                "engagement_project_count": project_total,
                "prevalence": round(prevalence.get(s, 0) / project_total, 3),
            }
            for s in signals
        ),
        key=lambda r: (r["prevalence"], r["signal_name"]),
    )

    # `all` — present on EVERY member; these define the shape.
    # `supporting` — present on some, weight scaled by how many.
    universal = [s for s in signals if member_total and member_counts.get(s, 0) >= member_total]
    partial = [s for s in signals if s not in universal]

    supporting = []
    for s in partial:
        share = member_counts.get(s, 0) / member_total if member_total else 0
        supporting.append(
            {"id": s.lower().replace("_", "-"), "signal": {"name": s}, "weight": max(5, int(round(share * 25 / 5)) * 5)}
        )

    metadata_conditions = []
    for facet, value in facets.items():
        field = _FACET_TO_METADATA_FIELD.get(facet)
        if field and value:
            metadata_conditions.append({"id": f"facet-{facet.replace('_', '-')}", "field": field, "equals": value})

    # Part E's scoring: base 50 for satisfying every required condition, plus
    # supporting weight capped at 50. A draft whose signals are ALL universal
    # — which is every single-member cluster, and many multi-member ones —
    # has an empty `supporting` group and can therefore never score above 50.
    # Defaulting minimumScore to 70 would emit a pattern that is structurally
    # incapable of matching anything, including the cluster it came from.
    # The threshold cannot sensibly exceed what a perfect match scores.
    achievable = 50 + min(50, sum(c["weight"] for c in supporting))
    minimum_score = min(70, achievable)

    slug = cluster.suggested_pattern_id or f"candidate-{cluster.cluster_id}"
    draft = {
        "id": slug,
        "name": cluster.suggested_name or f"Candidate shape {cluster.cluster_id}",
        "summary": cluster.suggested_description or "Discovered by step 5; not yet described.",
        "description": cluster.suggested_description or "",
        "category": "library",
        "classification_role": "PRIMARY",
        "classification_family": "APPLICATION_TYPE",
        "classification_value": slug.upper().replace("-", "_"),
        "priority": 50,
        "anchor_signals": [r["signal_name"] for r in ranking[:3]],
        "eligibility": {
            "fingerprintStatuses": ["COMPLETE", "PARTIAL"],
            "excludedProjectRoles": ["TEST", "DEPLOYMENT"],
        },
        "thresholds": {"minimumScore": minimum_score, "highConfidenceScore": 90},
        # Never `active`. It must be reviewed and promoted deliberately.
        "rules_status": "draft",
        "detection_rules": {
            "schema": "signal-rules/1.0",
            "all": [{"id": s.lower().replace("_", "-"), "signal": {"name": s}} for s in universal],
            "any": [],
            "atLeast": [],
            "supporting": supporting,
            "none": [],
            "metadata": metadata_conditions,
        },
    }

    notes = [
        "Draft only — nothing has been written to the catalog.",
        f"Anchors ranked by rarity across {project_total} project(s) in this engagement; "
        f"the least common signal makes the strongest anchor.",
        "rules_status is 'draft' and must be promoted deliberately after review.",
    ]
    if minimum_score < 70:
        notes.append(
            f"minimumScore is {minimum_score}, not the usual 70: every signal in this cluster is present on "
            f"every member, so they are all required conditions and nothing is left to score as supporting "
            f"evidence. A perfect match scores {achievable}. Raise the threshold only after adding supporting "
            f"signals, or the pattern can never match."
        )
    if not universal:
        notes.append(
            "No signal is present on every member, so the `all` group is empty and the pattern "
            "would match on supporting weight alone. Tighten it before promoting."
        )
    if cluster.is_singleton:
        notes.append("This cluster has a single member. One occurrence is not yet evidence of a pattern.")
    if cluster.cohesion is not None and float(cluster.cohesion) < 0.6:
        notes.append(
            f"Cohesion is {float(cluster.cohesion)}: the members are loosely related, so the shared "
            f"signature may describe none of them well."
        )
    notes.append(
        "After creating the pattern, re-run classification for this engagement to see whether it "
        "captures its cluster. No repository rescan is needed — classification reads stored fingerprints."
    )

    return DraftPatternOut(
        cluster_id=cluster_id,
        is_draft=True,
        pattern=draft,
        anchor_ranking=ranking,
        notes=notes,
    )


@router.post(
    "/{engagement_id}/pattern-candidates/{cluster_id}/merge-proposal",
    response_model=MergeProposalOut,
    summary="Propose a rule amendment merging a cluster into an existing pattern",
    response_description="The suggested diff. The target pattern is not modified.",
    operation_id="merge_proposal",
    responses={404: {"model": ErrorResponse, "description": "No such engagement, cluster or pattern."}},
)
def merge_proposal(
    engagement_id: str,
    cluster_id: str,
    pattern_id: str = Query(description="The pattern to widen."),
    db: Session = Depends(get_db),
):
    """
    Produces a diff and **does not apply it**.

    Widening a pattern to absorb a cluster changes classification for every
    project already matching it, across every engagement — patterns are
    master-catalog and client-agnostic. That is a catalog edit deserving its
    own review, not a side effect of a queue action. The `impact` block
    below is there so the reviewer can see how far it reaches before
    deciding.

    The cluster is still marked `merged` when the decision is applied: the
    question *what is this shape* has been answered, whether or not anyone
    widens the rule.
    """
    cluster = _require_cluster(db, engagement_id, cluster_id)
    pattern = db.get(models.Pattern, pattern_id)
    if pattern is None or pattern.deleted_at is not None:
        raise error(404, f"No pattern '{pattern_id}'", code="NOT_FOUND")

    rules = pattern.detection_rules or {}
    covered: set[str] = set(pattern.anchor_signals or [])
    for group in ("all", "any", "supporting", "none"):
        for condition in rules.get(group) or []:
            covered.add(condition["signal"]["name"])
    for group in rules.get("atLeast") or []:
        for condition in group.get("of") or []:
            covered.add(condition["signal"]["name"])

    cluster_signals = list((cluster.canonical_signature or {}).get("signals") or [])
    missing = sorted(s for s in cluster_signals if s not in covered)
    already = sorted(s for s in cluster_signals if s in covered)

    member_counts, member_total = _member_signal_counts(db, cluster_id)
    proposed = [
        {
            "group": "supporting",
            "id": s.lower().replace("_", "-"),
            "signal": {"name": s},
            "weight": 10,
            "present_on_members": member_counts.get(s, 0),
            "of_members": member_total,
        }
        for s in missing
    ]

    # How far the edit reaches. Counted across the whole platform, not this
    # engagement, because the pattern is shared.
    currently_matching = db.scalar(
        select(func.count()).select_from(models.ProjectClassification)
        .where(models.ProjectClassification.primary_pattern_id == pattern_id)
    ) or 0

    notes = [
        "Proposal only — the target pattern has not been modified.",
        f"'{pattern_id}' is master-catalog and client-agnostic: widening it changes classification "
        f"for every engagement, not just this one.",
        "Apply it explicitly in the rule builder if you agree with the diff.",
    ]
    if not missing:
        notes.append(
            "The pattern's rules already reference every signal in this cluster, so no widening is "
            "needed — the cluster probably failed on a threshold or a disqualifier, not on coverage. "
            "Check the pattern's `none` group and minimumScore before editing."
        )

    return MergeProposalOut(
        cluster_id=cluster_id,
        pattern_id=pattern_id,
        applied=False,
        signals_missing_from_pattern=missing,
        signals_already_covered=already,
        proposed_additions=proposed,
        impact={
            "projects_currently_matching_pattern": currently_matching,
            "cluster_member_count": cluster.member_count,
            "pattern_rules_status": pattern.rules_status,
            "scope": "all engagements",
        },
        notes=notes,
    )
