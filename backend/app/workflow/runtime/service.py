"""Top-level runtime orchestration — launch, resume, stop — tying together
instance identity, precondition evaluation, and the sequential executor.
Callers (routers) own the transaction: this module flushes but never commits.
"""

import datetime
import uuid

from sqlalchemy.orm import Session

from app import models
from app.workflow.definition import service as definition_service
from app.workflow.definition.model import JobDefinitionFile
from app.workflow.runtime import executor, preconditions
from app.workflow.runtime.instance import get_or_create_instance, resolve_parameters
from app.workflow.runtime.schemas import (
    DiagnosticOut,
    JobExecutionOut,
    ProducedOutputRef,
    ResolvedInputRef,
    StepExecutionOut,
    StepSummary,
)

RESUMABLE_BATCH_STATUSES = ("FAILED", "STOPPED")
STOPPABLE_BATCH_STATUSES = ("STARTING", "STARTED")
RESTARTABLE_BATCH_STATUSES = ("FAILED",)


class PreconditionError(Exception):
    """Carries errors in this API's shared shape — see app/errors.py."""

    def __init__(self, failures: list[dict]):
        super().__init__("; ".join(f["message"] for f in failures))
        self.failures = failures


def _compute_step_policy_snapshot(
    db: Session, engagement_id: str | None, flow_step_names: list[str]
) -> dict[str, dict]:
    """Read once, at launch — 22-STEP-SEQUENCING-AND-POLICY.md Part C: "The
    policy is read once at job launch and snapshotted into the job execution
    context, so a policy change mid-execution cannot produce a run that
    half-honoured it." Only steps with an explicit policy row are included;
    absence means enabled, so most flows snapshot to `{}`."""
    if not engagement_id:
        return {}
    rows = (
        db.query(models.EngagementStepPolicy)
        .filter(
            models.EngagementStepPolicy.engagement_id == engagement_id,
            models.EngagementStepPolicy.step_name.in_(flow_step_names),
        )
        .all()
    )
    return {row.step_name: {"enabled": row.enabled, "reason": row.reason} for row in rows}


def _next_execution_number(db: Session, instance_id: uuid.UUID) -> int:
    current_max = (
        db.query(models.WfJobExecution.execution_number)
        .filter_by(job_instance_id=instance_id)
        .order_by(models.WfJobExecution.execution_number.desc())
        .limit(1)
        .scalar()
    )
    return (current_max or 0) + 1


def create_execution(
    db: Session, job_name: str, provided_parameters: dict, triggered_by: str = "api"
) -> tuple[models.WfJobExecution, models.WfJobInstance, JobDefinitionFile]:
    """Phase 1 of a launch: validates parameters and preconditions, resolves
    (or creates) the job instance, and creates the `STARTING` job execution
    row — but does not run it. Split out from `launch_job` so a caller that
    needs "synchronous creation, asynchronous execution"
    (15-REPOSITORY-INGEST-UI.md Part E) can commit this and hand the actual
    run off to `run_execution_in_background` via `BackgroundTasks`, while
    still returning a trackable `job_execution_id` in the response.
    """
    definition_row = definition_service.get_active_definition(db, job_name)
    if definition_row is None:
        raise LookupError(f"no active definition for job '{job_name}'")
    definition = JobDefinitionFile.model_validate(definition_row.definition)

    parameters = resolve_parameters(job_name, definition, provided_parameters)

    failures = preconditions.evaluate_preconditions(db, definition, parameters)
    if failures:
        raise PreconditionError(failures)

    instance, _created = get_or_create_instance(db, job_name, parameters)

    step_policy_snapshot = _compute_step_policy_snapshot(
        db, parameters.get("engagement_id"), _flow_step_names(definition)
    )

    job_execution = models.WfJobExecution(
        job_instance_id=instance.id,
        job_definition_id=definition_row.id,
        execution_number=_next_execution_number(db, instance.id),
        batch_status="STARTING",
        engine_version=executor.ENGINE_VERSION,
        triggered_by=triggered_by,
        execution_context={"step_policy_snapshot": step_policy_snapshot},
    )
    db.add(job_execution)
    db.flush()

    return job_execution, instance, definition


def launch_job(
    db: Session, job_name: str, provided_parameters: dict, triggered_by: str = "api"
) -> models.WfJobExecution:
    """Synchronous, end-to-end: creates and immediately runs the execution in
    the caller's own session/transaction. Used by the generic
    `POST /api/workflow/jobs/{name}/launch` endpoint, which has no
    async-execution requirement of its own."""
    job_execution, instance, definition = create_execution(
        db, job_name, provided_parameters, triggered_by
    )
    return executor.run_execution(db, job_execution, instance, definition)


def run_execution_in_background(
    job_execution_id: uuid.UUID, instance_id: uuid.UUID, definition_dict: dict
) -> None:
    """Runs a previously-created (and already-committed) execution to
    completion in its own database session. For use with FastAPI
    `BackgroundTasks`: the request-scoped session the route handler used is
    closed by the time a background task runs, so this cannot reuse it.

    Defensive: if the run itself raises unexpectedly, marks the execution
    FAILED rather than leaving it stuck in STARTING/STARTED — the startup
    reconciliation only catches executions orphaned by a process restart,
    not ones whose background task died while the process kept running.
    """
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        job_execution = db.get(models.WfJobExecution, job_execution_id)
        instance = db.get(models.WfJobInstance, instance_id)
        definition = JobDefinitionFile.model_validate(definition_dict)
        executor.run_execution(db, job_execution, instance, definition)
        db.commit()
    except Exception as exc:
        db.rollback()
        job_execution = db.get(models.WfJobExecution, job_execution_id)
        if job_execution is not None and job_execution.batch_status in ("STARTING", "STARTED"):
            job_execution.batch_status = "FAILED"
            job_execution.exit_status = "FAILED"
            job_execution.exit_message = f"background execution crashed: {type(exc).__name__}: {exc}"
            db.commit()
    finally:
        db.close()


def resume_execution(db: Session, execution_id: uuid.UUID) -> models.WfJobExecution:
    prior = db.get(models.WfJobExecution, execution_id)
    if prior is None:
        raise LookupError(f"execution '{execution_id}' not found")
    if prior.batch_status not in RESUMABLE_BATCH_STATUSES:
        raise ValueError(
            f"execution '{execution_id}' is {prior.batch_status}; only "
            f"{' or '.join(RESUMABLE_BATCH_STATUSES)} executions can be resumed"
        )

    instance = db.get(models.WfJobInstance, prior.job_instance_id)
    definition_row = db.get(models.WfJobDefinition, prior.job_definition_id)
    definition = JobDefinitionFile.model_validate(definition_row.definition)

    job_execution = models.WfJobExecution(
        job_instance_id=instance.id,
        job_definition_id=definition_row.id,
        execution_number=_next_execution_number(db, instance.id),
        batch_status="STARTING",
        engine_version=executor.ENGINE_VERSION,
        triggered_by="resume",
        execution_context=prior.execution_context or {},
    )
    db.add(job_execution)
    db.flush()

    return executor.run_execution(db, job_execution, instance, definition)


def stop_execution(db: Session, execution_id: uuid.UUID) -> models.WfJobExecution:
    execution = db.get(models.WfJobExecution, execution_id)
    if execution is None:
        raise LookupError(f"execution '{execution_id}' not found")
    if execution.batch_status not in STOPPABLE_BATCH_STATUSES:
        raise ValueError(
            f"execution '{execution_id}' is {execution.batch_status}; only "
            f"{' or '.join(STOPPABLE_BATCH_STATUSES)} executions can be stopped"
        )

    execution.batch_status = "STOPPED"
    execution.exit_message = "Stopped by operator request"
    execution.ended_at = datetime.datetime.now(datetime.timezone.utc)
    db.flush()
    return execution


def get_execution(db: Session, execution_id: uuid.UUID) -> models.WfJobExecution | None:
    return db.get(models.WfJobExecution, execution_id)


def get_job_name(db: Session, execution: models.WfJobExecution) -> str:
    instance = db.get(models.WfJobInstance, execution.job_instance_id)
    return instance.job_name if instance else ""


def _duration_seconds(started_at, ended_at) -> float | None:
    if started_at is None or ended_at is None:
        return None
    return round((ended_at - started_at).total_seconds(), 3)


def _resolved_context(db: Session, parameters: dict) -> dict[str, str]:
    """Turns opaque instance parameters into names — docs/20 Part A:
    'resolved_context is the important addition... Populate it by looking up
    whichever parameters are present; omit keys that do not apply.'"""
    context: dict[str, str] = {}

    engagement_id = parameters.get("engagement_id")
    if engagement_id:
        engagement = db.get(models.Engagement, engagement_id)
        if engagement is not None:
            context["engagement_name"] = engagement.client_name

    repository_id = parameters.get("repository_id")
    if repository_id:
        try:
            repo = db.get(models.Repository, repository_id)
        except Exception:
            repo = None
        if repo is not None:
            context["repository_slug"] = repo.slug
            context["repository_name"] = repo.name

    return context


def _flow_step_names(definition: JobDefinitionFile) -> list[str]:
    """Ordered step names in this definition's flow. Splits/deciders are
    deferred to E8 — every flow entry today is a plain step."""
    return [node.step for node in definition.flow]


def _compute_step_summary(step_rows: list[models.WfStepExecution], flow_step_names: list[str]) -> StepSummary:
    completed = sum(1 for s in step_rows if s.exit_status == "COMPLETED")
    not_implemented = sum(1 for s in step_rows if s.exit_status == "NOT_IMPLEMENTED")
    skipped = sum(1 for s in step_rows if s.exit_status == "SKIPPED")
    failed = sum(1 for s in step_rows if s.batch_status == "FAILED")
    total = len(flow_step_names) or len(step_rows)
    pending = max(0, total - len(step_rows))
    return StepSummary(
        total=total,
        completed=completed,
        not_implemented=not_implemented,
        skipped=skipped,
        failed=failed,
        pending=pending,
    )


def to_execution_out(db: Session, execution: models.WfJobExecution) -> JobExecutionOut:
    """`job_name` isn't a column on wf_job_executions — it's joined from the
    instance — so this can't be a plain `model_validate(execution)`. Also
    joins the definition version, resolves parameter UUIDs to names, and
    rolls up step/artifact counts (docs/20 Part A)."""
    instance = db.get(models.WfJobInstance, execution.job_instance_id)
    definition_row = db.get(models.WfJobDefinition, execution.job_definition_id)
    definition = JobDefinitionFile.model_validate(definition_row.definition) if definition_row else None

    step_rows = (
        db.query(models.WfStepExecution)
        .filter_by(job_execution_id=execution.id)
        .order_by(models.WfStepExecution.started_at)
        .all()
    )
    flow_step_names = _flow_step_names(definition) if definition else [s.step_name for s in step_rows]
    artifact_count = (
        db.query(models.WfArtifact).filter_by(job_execution_id=execution.id).count()
    )

    return JobExecutionOut(
        id=execution.id,
        job_name=instance.job_name if instance else "",
        job_instance_id=execution.job_instance_id,
        job_definition_id=execution.job_definition_id,
        job_definition_version=definition_row.version if definition_row else 0,
        execution_number=execution.execution_number,
        batch_status=execution.batch_status,
        exit_status=execution.exit_status,
        exit_message=execution.exit_message,
        execution_context=execution.execution_context or {},
        parameters=instance.parameters if instance else {},
        engine_version=execution.engine_version,
        triggered_by=execution.triggered_by,
        started_at=execution.started_at,
        ended_at=execution.ended_at,
        duration_seconds=_duration_seconds(execution.started_at, execution.ended_at),
        created_at=execution.created_at,
        resolved_context=_resolved_context(db, instance.parameters if instance else {}),
        step_summary=_compute_step_summary(step_rows, flow_step_names),
        artifact_count=artifact_count,
        can_restart=execution.batch_status in RESTARTABLE_BATCH_STATUSES,
        can_resume=execution.batch_status == "STOPPED",
    )


def list_executions(
    db: Session,
    job_name: str | None = None,
    batch_status: str | None = None,
    engagement_id: str | None = None,
    repository_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[models.WfJobExecution]:
    """`engagement_id`/`repository_id` match inside `wf_job_instances.parameters`
    — they only ever match jobs that declare those parameters. A job like
    `trackB-wave`, scoped to a wave with no `repository_id` at all, simply
    won't match a `repository_id` filter."""
    query = db.query(models.WfJobExecution).join(
        models.WfJobInstance, models.WfJobExecution.job_instance_id == models.WfJobInstance.id
    )
    if job_name:
        query = query.filter(models.WfJobInstance.job_name == job_name)
    if batch_status:
        query = query.filter(models.WfJobExecution.batch_status == batch_status)
    if engagement_id:
        query = query.filter(models.WfJobInstance.parameters["engagement_id"].astext == engagement_id)
    if repository_id:
        query = query.filter(models.WfJobInstance.parameters["repository_id"].astext == repository_id)
    return (
        query.order_by(models.WfJobExecution.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


def get_step_executions(db: Session, execution_id: uuid.UUID) -> list[models.WfStepExecution]:
    return (
        db.query(models.WfStepExecution)
        .filter_by(job_execution_id=execution_id)
        .order_by(models.WfStepExecution.started_at)
        .all()
    )


def to_step_execution_out(
    db: Session,
    step_execution: models.WfStepExecution,
    sequence: int,
    registration: models.WfStepRegistration | None = None,
) -> StepExecutionOut:
    """Joins `wf_step_registrations` for display metadata, and `wf_artifacts`
    for outputs actually produced by this step execution (docs/20 Part A)."""
    if registration is None:
        registration = db.get(models.WfStepRegistration, step_execution.step_name)

    outputs = (
        db.query(models.WfArtifact).filter_by(step_execution_id=step_execution.id).order_by(models.WfArtifact.created_at).all()
    )

    return StepExecutionOut(
        step_execution_id=step_execution.id,
        job_execution_id=step_execution.job_execution_id,
        step_name=step_execution.step_name,
        lifecycle_step_no=registration.lifecycle_step_no if registration else None,
        display_name=registration.display_name if registration else step_execution.step_name,
        owner_code=registration.owner_code if registration else "",
        step_version=step_execution.step_version,
        adapter_type=registration.adapter_type if registration else "",
        implementation_status=registration.implementation_status if registration else "",
        sequence=sequence,
        partition_key=step_execution.partition_key,
        attempt=step_execution.attempt,
        batch_status=step_execution.batch_status,
        exit_status=step_execution.exit_status,
        exit_message=step_execution.exit_message,
        skip_reason=step_execution.skip_reason,
        metrics={
            "read_count": step_execution.read_count,
            "write_count": step_execution.write_count,
            "skip_count": step_execution.skip_count,
            "commit_count": step_execution.commit_count,
        },
        started_at=step_execution.started_at,
        ended_at=step_execution.ended_at,
        duration_seconds=_duration_seconds(step_execution.started_at, step_execution.ended_at),
        diagnostics=[DiagnosticOut(**d) for d in (step_execution.diagnostics or [])],
        inputs_resolved=[ResolvedInputRef(**r) for r in (step_execution.inputs_resolved or [])],
        outputs_produced=[
            ProducedOutputRef(artifact_id=a.id, artifact_type=a.artifact_type, artifact_version=a.artifact_version)
            for a in outputs
        ],
        stdout_tail=step_execution.stdout_tail,
        stderr_tail=step_execution.stderr_tail,
        working_dir=step_execution.working_dir,
        carried_forward=step_execution.carried_forward,
    )


def to_step_execution_outs(db: Session, execution: models.WfJobExecution) -> list[StepExecutionOut]:
    """All step executions for one job execution, enriched, in flow order —
    `sequence` reflects the job definition's declared step order, not
    started_at, so a not-yet-reached step still sorts correctly relative to
    its siblings once it appears."""
    definition_row = db.get(models.WfJobDefinition, execution.job_definition_id)
    definition = JobDefinitionFile.model_validate(definition_row.definition) if definition_row else None
    flow_step_names = _flow_step_names(definition) if definition else []
    sequence_by_name = {name: i + 1 for i, name in enumerate(flow_step_names)}

    step_rows = get_step_executions(db, execution.id)
    registrations = {
        row.step_name: row
        for row in db.query(models.WfStepRegistration).filter(
            models.WfStepRegistration.step_name.in_({s.step_name for s in step_rows})
        )
    }

    outs = [
        to_step_execution_out(
            db, step, sequence_by_name.get(step.step_name, i + 1), registrations.get(step.step_name)
        )
        for i, step in enumerate(step_rows)
    ]
    outs.sort(key=lambda s: s.sequence)
    return outs
