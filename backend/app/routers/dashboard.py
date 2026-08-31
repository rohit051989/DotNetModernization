"""Engagement dashboard — see 16-DASHBOARD-SPEC.md. Read-only: no mutations
from this tab.

`null` vs `0` is load-bearing throughout this module: a section is `null`
when no implemented step produces it yet, and becomes a real object once the
producing step exists. Never fabricate a zero for an unimplemented capability.
"""

import datetime
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.classification import service as classification_service
from app.db import get_db
from app.errors import ErrorResponse, error
from app.routers.engagements import compute_coverage
from app.structure import service as structure_service
from app.workflow.runtime import service as runtime_service

router = APIRouter(prefix="/api/engagements", tags=["Dashboard"])

_DISCOVERY_JOB = "phase0-repository-discovery"
_NOT_FOUND = {"model": ErrorResponse, "description": "No engagement exists with this id."}

# capability name -> the step_name that must be implemented to unlock it.
_CAPABILITY_STEP = {
    "application_count": "application-fingerprinting",
    "pattern_classification": "pattern-classification",
    "impact_map": "impact-map-generation",
    "test_coverage": "test-coverage-assessment",
    "risk_tier": "risk-scoring-tier-assignment",
    "wave_planning": "migration-wave-planning",
}


# ---------- Schemas ----------


class RepositoryCounts(BaseModel):
    total: int = Field(description="Non-deleted repositories registered in this engagement.")
    registered: int = Field(description="Repositories with ingest_status 'registered' — not yet scanned.")
    scanned: int = Field(description="Repositories with ingest_status 'scanned'.")
    scan_failed: int = Field(description="Repositories with ingest_status 'scan_failed'.")
    path_missing: int = Field(description="Repositories with ingest_status 'path_missing'.")
    total_size_bytes: int = Field(description="Sum of size_bytes across all repositories with a known size.")
    with_git_history: int = Field(description="Repositories where has_git_history is true.")


class DiscoveryCounts(BaseModel):
    not_started: int = Field(description="Repositories with no phase0-repository-discovery execution yet.")
    in_progress: int = Field(description="Repositories whose latest execution is non-terminal.")
    completed: int = Field(description="Repositories whose latest execution is COMPLETED.")
    failed: int = Field(description="Repositories whose latest execution is FAILED or ABANDONED.")
    awaiting_approval: int = Field(description="Repositories whose latest execution is STOPPED.")


class DecisionCounts(BaseModel):
    total_patterns_in_scope: int = Field(description="Matches GET /api/engagements/{eid}/coverage's total_patterns exactly.")
    approved: int
    in_review: int
    parked: int
    deferred: int


class StructureCounts(BaseModel):
    """Real (not null) once solution-discovery — lifecycle step 2 — is
    implemented, unlike `applications`/`patterns`/`risk_tiers`/`waves` below.
    Zero repositories scanned yet is a legitimate zero, not an unimplemented
    capability, so this is never null."""

    repositories_scanned: int = Field(description="Repositories with a repository_structure row — solution-discovery has run.")
    solution_count: int = Field(description="Sum of solutions found across scanned repositories.")
    project_file_count: int = Field(description="Sum of project files found across scanned repositories.")
    standalone_project_count: int = Field(description="Sum of projects referenced by no solution.")
    unresolved_reference_count: int = Field(description="Sum of solution/project references that did not resolve.")
    legacy_project_count: int = Field(description="Sum of projects with project_format 'legacy_msbuild'.")
    sdk_project_count: int = Field(description="Sum of projects with project_format 'sdk_style'.")
    framework_families: dict[str, int] = Field(description="Project count per normalised framework family, summed across repositories.")


class TopPattern(BaseModel):
    pattern_id: str
    pattern_name: str
    count: int


class PatternCounts(BaseModel):
    """The dashboard's Patterns card, real once pattern-classification (step
    4) is implemented. Deliberately labelled 'projects classified as', never
    'applications' — deployable-application aggregation is a different,
    still-unimplemented rollup (see `applications` above)."""

    projects_evaluated: int = Field(description="Projects with any classification result, across every repository in this engagement.")
    projects_matched: int = Field(description="Projects with classification_status MATCHED or MULTIPLE_MATCHES.")
    projects_ambiguous: int = Field(description="Projects with classification_status AMBIGUOUS.")
    projects_no_pattern_matched: int = Field(description="Projects with classification_status NO_PATTERN_MATCHED — step 5 candidates.")
    top_patterns: list[TopPattern] = Field(description="Most common primary patterns, highest count first.")


class DashboardCapabilities(BaseModel):
    application_count: bool = Field(description="True once 'application-fingerprinting' (step 3) is implemented.")
    pattern_classification: bool = Field(description="True once 'pattern-classification' (step 4) is implemented.")
    impact_map: bool = Field(description="True once 'impact-map-generation' (step 8) is implemented.")
    test_coverage: bool = Field(description="True once 'test-coverage-assessment' (step 9) is implemented.")
    risk_tier: bool = Field(description="True once 'risk-scoring-tier-assignment' (step 10) is implemented.")
    wave_planning: bool = Field(description="True once 'migration-wave-planning' (step 12) is implemented.")


class RecentExecution(BaseModel):
    job_execution_id: str
    job_name: str
    repository_slug: str | None = Field(description="Null if this job instance declares no repository_id.")
    batch_status: str
    exit_status: str | None
    steps_completed: int = Field(description="Steps whose exit_status is COMPLETED — real completions, not stub pass-throughs.")
    steps_total: int
    started_at: datetime.datetime | None
    ended_at: datetime.datetime | None


class DashboardSummary(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "engagement_id": "client-a-ocp4",
                    "client_name": "Client A",
                    "generated_at": "2026-08-05T12:00:00Z",
                    "repositories": {
                        "total": 4,
                        "registered": 1,
                        "scanned": 3,
                        "scan_failed": 0,
                        "path_missing": 0,
                        "total_size_bytes": 184320512,
                        "with_git_history": 3,
                    },
                    "discovery": {
                        "not_started": 0,
                        "in_progress": 1,
                        "completed": 3,
                        "failed": 0,
                        "awaiting_approval": 0,
                    },
                    "structure": {
                        "repositories_scanned": 3,
                        "solution_count": 5,
                        "project_file_count": 42,
                        "standalone_project_count": 6,
                        "unresolved_reference_count": 2,
                        "legacy_project_count": 30,
                        "sdk_project_count": 12,
                        "framework_families": {"net-framework": 30, "net": 12},
                    },
                    "applications": None,
                    "patterns": None,
                    "risk_tiers": None,
                    "waves": None,
                    "decisions": {
                        "total_patterns_in_scope": 8,
                        "approved": 5,
                        "in_review": 1,
                        "parked": 2,
                        "deferred": 0,
                    },
                    "capabilities": {
                        "application_count": False,
                        "pattern_classification": False,
                        "impact_map": False,
                        "test_coverage": False,
                        "risk_tier": False,
                        "wave_planning": False,
                    },
                    "recent_executions": [],
                }
            ]
        }
    )

    engagement_id: str
    client_name: str = Field(description="Denormalised for display.")
    generated_at: str = Field(description="ISO-8601 UTC timestamp this snapshot was computed.")
    repositories: RepositoryCounts
    discovery: DiscoveryCounts
    structure: StructureCounts = Field(description="Solution/project discovery rollup — see 19-STEP-002-SOLUTION-DISCOVERY.md.")
    applications: dict | None = Field(default=None, description="Null — no step producing application rollups is implemented yet.")
    patterns: PatternCounts | None = Field(default=None, description="Null until pattern-classification (step 4) is implemented; real thereafter.")
    risk_tiers: dict | None = Field(default=None, description="Null — no step producing risk tiers is implemented yet.")
    waves: dict | None = Field(default=None, description="Null — no step producing wave status is implemented yet.")
    decisions: DecisionCounts = Field(description="Real now — computed the same way as GET /api/engagements/{eid}/coverage.")
    capabilities: DashboardCapabilities
    recent_executions: list[RecentExecution] = Field(description="Last 10 executions across every job for this engagement.")


class StepBrief(BaseModel):
    """Per-segment detail for the discovery progress bar's tooltip — see
    20-WORKFLOW-OBSERVABILITY-UI.md Part C: 'Each segment tooltips with its
    step name and status.'"""

    step_name: str
    display_name: str
    batch_status: str
    exit_status: str | None
    skip_reason: str | None = Field(
        description="Populated only when exit_status is SKIPPED — see 22-STEP-SEQUENCING-AND-POLICY.md Part D."
    )


class LatestExecutionInfo(BaseModel):
    job_execution_id: str
    batch_status: str
    exit_status: str | None
    steps_completed: int
    steps_not_implemented: int
    steps_skipped: int = Field(description="Steps whose exit_status is SKIPPED.")
    steps_failed: int
    steps_total: int
    current_step: str | None = Field(description="The step currently STARTED, or null if none is running.")
    steps: list[StepBrief] = Field(default_factory=list, description="Every step recorded so far, in start order.")
    started_at: datetime.datetime | None
    ended_at: datetime.datetime | None


class RepositoryStructureBrief(BaseModel):
    """Per-row summary for the dashboard's repository table columns. Null
    when solution-discovery has not run for this repository yet."""

    scan_status: str = Field(description="'complete', 'partial', or 'failed'.")
    solution_count: int | None
    project_file_count: int | None
    standalone_project_count: int | None
    framework_families: dict[str, int] = Field(description="Project count per normalised framework family.")


class DashboardRepositoryRow(BaseModel):
    repository_id: str
    slug: str
    name: str
    source_type: str
    provider: str | None
    ingest_status: str
    has_git_history: bool
    ingest_commit_sha: str | None
    size_bytes: int | None
    file_count: int | None
    last_ingested_at: datetime.datetime | None = Field(description="repositories.last_scanned_at.")
    latest_execution: LatestExecutionInfo | None = Field(description="Null if discovery has never run for this repository.")
    structure: RepositoryStructureBrief | None = Field(default=None, description="Null until solution-discovery has run for this repository.")
    application_count: int | None = Field(default=None, description="Null — awaiting application fingerprinting (step 3).")
    patterns_identified: int | None = Field(default=None, description="Null — awaiting pattern classification (step 4).")
    highest_risk_tier: str | None = Field(default=None, description="Null — awaiting risk scoring (step 10).")
    wave: str | None = Field(default=None, description="Null — awaiting wave planning (step 12).")


class DashboardRepositoriesResponse(BaseModel):
    repositories: list[DashboardRepositoryRow]


# ---------- Helpers ----------


def _iso_utc(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _step_progress(db: Session, execution_id: uuid.UUID) -> tuple[int, int, int, int, int, str | None]:
    """(completed, not_implemented, skipped, failed, total, current_step).
    Buckets by exit_status, not batch_status — a NOT_IMPLEMENTED (or
    SKIPPED) step has batch_status COMPLETED in the engine's own
    bookkeeping, but neither is a real completion for dashboard purposes."""
    steps = db.query(models.WfStepExecution).filter_by(job_execution_id=execution_id).all()
    completed = sum(1 for s in steps if s.exit_status == "COMPLETED")
    not_implemented = sum(1 for s in steps if s.exit_status == "NOT_IMPLEMENTED")
    skipped = sum(1 for s in steps if s.exit_status == "SKIPPED")
    failed = sum(1 for s in steps if s.batch_status == "FAILED")
    current_step = next((s.step_name for s in steps if s.batch_status == "STARTED"), None)
    return completed, not_implemented, skipped, failed, len(steps), current_step


def _step_briefs(db: Session, execution_id: uuid.UUID) -> list[StepBrief]:
    steps = (
        db.query(models.WfStepExecution)
        .filter_by(job_execution_id=execution_id)
        .order_by(models.WfStepExecution.started_at)
        .all()
    )
    registrations = {
        row.step_name: row
        for row in db.query(models.WfStepRegistration).filter(
            models.WfStepRegistration.step_name.in_({s.step_name for s in steps})
        )
    }
    return [
        StepBrief(
            step_name=s.step_name,
            display_name=registrations[s.step_name].display_name if s.step_name in registrations else s.step_name,
            batch_status=s.batch_status,
            exit_status=s.exit_status,
            skip_reason=s.skip_reason,
        )
        for s in steps
    ]


def _latest_discovery_by_repository(db: Session, engagement_id: str) -> dict[str, models.WfJobExecution]:
    """The most recent phase0-repository-discovery execution per repository_id."""
    executions = runtime_service.list_executions(
        db, job_name=_DISCOVERY_JOB, engagement_id=engagement_id, limit=1000
    )
    latest: dict[str, models.WfJobExecution] = {}
    for execution in executions:
        instance = db.get(models.WfJobInstance, execution.job_instance_id)
        repository_id = (instance.parameters or {}).get("repository_id") if instance else None
        if repository_id and repository_id not in latest:
            latest[repository_id] = execution
    return latest


def _discovery_bucket(execution: models.WfJobExecution | None) -> str:
    if execution is None:
        return "not_started"
    if execution.batch_status == "COMPLETED":
        return "completed"
    if execution.batch_status in ("FAILED", "ABANDONED"):
        return "failed"
    if execution.batch_status == "STOPPED":
        return "awaiting_approval"
    return "in_progress"  # STARTING, STARTED, STOPPING


def _get_engagement(db: Session, engagement_id: str) -> models.Engagement:
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None or engagement.deleted_at is not None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    return engagement


# ---------- Routes ----------


@router.get(
    "/{engagement_id}/dashboard",
    response_model=DashboardSummary,
    summary="Get the engagement dashboard summary",
    response_description="One payload covering repository, discovery, decision and capability status for this engagement.",
    operation_id="get_engagement_dashboard",
    responses={404: _NOT_FOUND},
)
def get_dashboard(engagement_id: str, db: Session = Depends(get_db)):
    """
    Assembled in one call so the frontend never has to stitch together
    several endpoints for a single screen. `applications`, `patterns`,
    `risk_tiers` and `waves` are `null` — not zeroed objects — because no
    implemented step produces them yet; `decisions` is real, computed
    identically to `GET /api/engagements/{eid}/coverage`.
    """
    engagement = _get_engagement(db, engagement_id)

    repos = (
        db.query(models.Repository)
        .filter(models.Repository.engagement_id == engagement_id, models.Repository.deleted_at.is_(None))
        .all()
    )
    # Repositories with retirement_status other than 'active' are still
    # registered and scanned — the inventory is useful — but are excluded
    # from modernization scope counts here (15-REPOSITORY-INGEST-UI.md
    # Part C). The repository list itself (dashboard/repositories,
    # GET .../repositories) still shows them, muted.
    scoped_repos = [r for r in repos if r.retirement_status == "active"]

    repository_counts = RepositoryCounts(
        total=len(scoped_repos),
        registered=sum(1 for r in scoped_repos if r.ingest_status == "registered"),
        scanned=sum(1 for r in scoped_repos if r.ingest_status == "scanned"),
        scan_failed=sum(1 for r in scoped_repos if r.ingest_status == "scan_failed"),
        path_missing=sum(1 for r in scoped_repos if r.ingest_status == "path_missing"),
        total_size_bytes=sum(r.size_bytes or 0 for r in scoped_repos),
        with_git_history=sum(1 for r in scoped_repos if r.has_git_history),
    )

    latest_by_repo = _latest_discovery_by_repository(db, engagement_id)
    buckets = {"not_started": 0, "in_progress": 0, "completed": 0, "failed": 0, "awaiting_approval": 0}
    for repo in scoped_repos:
        buckets[_discovery_bucket(latest_by_repo.get(str(repo.id)))] += 1
    discovery_counts = DiscoveryCounts(**buckets)

    coverage = compute_coverage(db, engagement_id)
    decisions = DecisionCounts(
        total_patterns_in_scope=coverage.total_patterns,
        approved=coverage.approved,
        in_review=coverage.in_review,
        parked=coverage.parked,
        deferred=coverage.deferred,
    )

    implemented_step_names = {
        row.step_name
        for row in db.query(models.WfStepRegistration).filter(
            models.WfStepRegistration.implementation_status == "implemented"
        )
    }
    capabilities = DashboardCapabilities(
        **{name: step in implemented_step_names for name, step in _CAPABILITY_STEP.items()}
    )

    structure_summary = structure_service.get_engagement_structure_summary(db, engagement_id)
    structure_counts = StructureCounts(**{k: v for k, v in structure_summary.items() if k != "engagement_id"})

    pattern_counts = None
    if capabilities.pattern_classification:
        distribution = classification_service.pattern_distribution(db, engagement_id)
        if distribution["projects_evaluated"] > 0:
            summary = classification_service.classification_summary_across(db, engagement_id)
            pattern_counts = PatternCounts(
                projects_evaluated=distribution["projects_evaluated"],
                projects_matched=summary["matched"] + summary["multiple_matches"],
                projects_ambiguous=summary["ambiguous"],
                projects_no_pattern_matched=summary["no_pattern_matched"],
                top_patterns=[TopPattern(**p) for p in distribution["primary_pattern_distribution"][:5]],
            )

    slugs_by_id = {str(r.id): r.slug for r in repos}
    recent_executions = []
    for execution in runtime_service.list_executions(db, engagement_id=engagement_id, limit=10):
        instance = db.get(models.WfJobInstance, execution.job_instance_id)
        repository_id = (instance.parameters or {}).get("repository_id") if instance else None
        completed, _not_impl, _skipped, _failed, total, _current = _step_progress(db, execution.id)
        recent_executions.append(
            RecentExecution(
                job_execution_id=str(execution.id),
                job_name=runtime_service.get_job_name(db, execution),
                repository_slug=slugs_by_id.get(repository_id),
                batch_status=execution.batch_status,
                exit_status=execution.exit_status,
                steps_completed=completed,
                steps_total=total,
                started_at=execution.started_at,
                ended_at=execution.ended_at,
            )
        )

    return DashboardSummary(
        engagement_id=engagement_id,
        client_name=engagement.client_name,
        generated_at=_iso_utc(datetime.datetime.now(datetime.timezone.utc)),
        repositories=repository_counts,
        discovery=discovery_counts,
        structure=structure_counts,
        applications=None,
        patterns=pattern_counts,
        risk_tiers=None,
        waves=None,
        decisions=decisions,
        capabilities=capabilities,
        recent_executions=recent_executions,
    )


@router.get(
    "/{engagement_id}/dashboard/repositories",
    response_model=DashboardRepositoriesResponse,
    summary="Get per-repository dashboard rows",
    response_description="One row per repository, with discovery progress, sortable and filterable independently of the summary.",
    operation_id="get_engagement_dashboard_repositories",
    responses={404: _NOT_FOUND},
)
def get_dashboard_repositories(
    engagement_id: str,
    ingest_status: str | None = Query(None, description="Filter by 'registered', 'scanned', 'scan_failed', or 'path_missing'."),
    discovery_status: str | None = Query(
        None, description="Filter by 'not_started', 'in_progress', 'completed', 'failed', or 'awaiting_approval'."
    ),
    q: str | None = Query(None, description="Case-insensitive substring match against name and slug."),
    sort: str | None = Query(None, description="Column to sort by: 'name', 'size_bytes', or 'last_scanned_at'. Prefix with '-' to reverse."),
    db: Session = Depends(get_db),
):
    """Separate from the summary so the table can be sorted, filtered and
    paginated without recomputing aggregates."""
    _get_engagement(db, engagement_id)

    query = db.query(models.Repository).filter(
        models.Repository.engagement_id == engagement_id, models.Repository.deleted_at.is_(None)
    )
    if ingest_status:
        query = query.filter(models.Repository.ingest_status == ingest_status)
    if q:
        like = f"%{q}%"
        query = query.filter(models.Repository.name.ilike(like) | models.Repository.slug.ilike(like))
    repos = query.all()

    sort_key = sort.lstrip("-") if sort else "name"
    reverse = bool(sort and sort.startswith("-"))
    sort_fns = {
        "name": lambda r: (r.name or "").lower(),
        "size_bytes": lambda r: r.size_bytes or 0,
        "last_scanned_at": lambda r: r.last_scanned_at or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
    }
    repos.sort(key=sort_fns.get(sort_key, sort_fns["name"]), reverse=reverse)

    latest_by_repo = _latest_discovery_by_repository(db, engagement_id)
    structure_by_repo = {
        row.repository_id: row
        for row in db.query(models.RepositoryStructure).filter(
            models.RepositoryStructure.repository_id.in_([r.id for r in repos])
        )
    } if repos else {}

    pattern_counts_implemented = (
        db.get(models.WfStepRegistration, "pattern-classification").implementation_status == "implemented"
    )
    patterns_identified_by_repo: dict[uuid.UUID, int] = {}
    if repos and pattern_counts_implemented:
        for repo_id, count in (
            db.query(models.ProjectClassification.repository_id, func.count(models.ProjectClassification.project_id))
            .filter(
                models.ProjectClassification.repository_id.in_([r.id for r in repos]),
                models.ProjectClassification.classification_status.in_(["MATCHED", "MULTIPLE_MATCHES"]),
            )
            .group_by(models.ProjectClassification.repository_id)
        ):
            patterns_identified_by_repo[repo_id] = count

    rows = []
    for repo in repos:
        execution = latest_by_repo.get(str(repo.id))
        bucket = _discovery_bucket(execution)
        if discovery_status and bucket != discovery_status:
            continue

        structure_row = structure_by_repo.get(repo.id)
        structure_brief = (
            RepositoryStructureBrief(
                scan_status=structure_row.scan_status,
                solution_count=structure_row.solution_count,
                project_file_count=structure_row.project_file_count,
                standalone_project_count=structure_row.standalone_project_count,
                framework_families=structure_row.framework_families or {},
            )
            if structure_row is not None
            else None
        )

        latest_execution = None
        if execution is not None:
            completed, not_implemented, skipped, failed, total, current_step = _step_progress(db, execution.id)
            latest_execution = LatestExecutionInfo(
                job_execution_id=str(execution.id),
                batch_status=execution.batch_status,
                exit_status=execution.exit_status,
                steps_completed=completed,
                steps_not_implemented=not_implemented,
                steps_skipped=skipped,
                steps_failed=failed,
                steps_total=total,
                current_step=current_step,
                steps=_step_briefs(db, execution.id),
                started_at=execution.started_at,
                ended_at=execution.ended_at,
            )

        rows.append(
            DashboardRepositoryRow(
                repository_id=str(repo.id),
                slug=repo.slug,
                name=repo.name,
                source_type=repo.source_type,
                provider=repo.provider,
                ingest_status=repo.ingest_status,
                has_git_history=repo.has_git_history,
                ingest_commit_sha=repo.ingest_commit_sha,
                size_bytes=repo.size_bytes,
                file_count=repo.file_count,
                last_ingested_at=repo.last_scanned_at,
                latest_execution=latest_execution,
                structure=structure_brief,
                patterns_identified=patterns_identified_by_repo.get(repo.id, 0) if pattern_counts_implemented else None,
            )
        )

    return DashboardRepositoriesResponse(repositories=rows)
