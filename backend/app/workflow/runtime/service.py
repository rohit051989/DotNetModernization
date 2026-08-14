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
from app.workflow.runtime.schemas import JobExecutionOut

RESUMABLE_BATCH_STATUSES = ("FAILED", "STOPPED")
STOPPABLE_BATCH_STATUSES = ("STARTING", "STARTED")


class PreconditionError(Exception):
    """Carries errors in this API's shared shape — see app/errors.py."""

    def __init__(self, failures: list[dict]):
        super().__init__("; ".join(f["message"] for f in failures))
        self.failures = failures


def _next_execution_number(db: Session, instance_id: uuid.UUID) -> int:
    current_max = (
        db.query(models.WfJobExecution.execution_number)
        .filter_by(job_instance_id=instance_id)
        .order_by(models.WfJobExecution.execution_number.desc())
        .limit(1)
        .scalar()
    )
    return (current_max or 0) + 1


def launch_job(
    db: Session, job_name: str, provided_parameters: dict, triggered_by: str = "api"
) -> models.WfJobExecution:
    definition_row = definition_service.get_active_definition(db, job_name)
    if definition_row is None:
        raise LookupError(f"no active definition for job '{job_name}'")
    definition = JobDefinitionFile.model_validate(definition_row.definition)

    parameters = resolve_parameters(job_name, definition, provided_parameters)

    failures = preconditions.evaluate_preconditions(db, definition, parameters)
    if failures:
        raise PreconditionError(failures)

    instance, _created = get_or_create_instance(db, job_name, parameters)

    job_execution = models.WfJobExecution(
        job_instance_id=instance.id,
        job_definition_id=definition_row.id,
        execution_number=_next_execution_number(db, instance.id),
        batch_status="STARTING",
        engine_version=executor.ENGINE_VERSION,
        triggered_by=triggered_by,
        execution_context={},
    )
    db.add(job_execution)
    db.flush()

    return executor.run_execution(db, job_execution, instance, definition)


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


def to_execution_out(db: Session, execution: models.WfJobExecution) -> JobExecutionOut:
    """`job_name` isn't a column on wf_job_executions — it's joined from the
    instance — so this can't be a plain `model_validate(execution)`."""
    return JobExecutionOut(
        id=execution.id,
        job_name=get_job_name(db, execution),
        job_instance_id=execution.job_instance_id,
        job_definition_id=execution.job_definition_id,
        execution_number=execution.execution_number,
        batch_status=execution.batch_status,
        exit_status=execution.exit_status,
        exit_message=execution.exit_message,
        execution_context=execution.execution_context or {},
        engine_version=execution.engine_version,
        triggered_by=execution.triggered_by,
        started_at=execution.started_at,
        ended_at=execution.ended_at,
        created_at=execution.created_at,
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
