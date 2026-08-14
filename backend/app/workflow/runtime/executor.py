"""The sequential execution engine — see 10-ENGINE-CONCEPTS.md and
12-JOB-DEFINITION-FORMAT.md.

Splits, deciders and partitioning are deferred to E8: `_flat_step_nodes`
raises clearly if the flow contains anything but a plain sequence of steps.

Restart semantics (10-ENGINE-CONCEPTS.md): a new job execution for an
existing instance resumes from the first step that was NOT `COMPLETED` in
the previous execution (or that declares `allow_start_if_complete: true`).
Everything before that point is carried forward into the new execution as-is
— including its artifacts — so a query scoped to one job_execution_id always
shows the instance's full current picture, not just what changed this
attempt.
"""

import datetime
import re
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.workflow import semver
from app.workflow.adapters import create_adapter
from app.workflow.contract import ArtifactRef, StepContext, StepResult
from app.workflow.definition.model import JobDefinitionFile, StepNode

DEFAULT_START_LIMIT = 3
ENGINE_VERSION = "0.1.0"

_INPUT_REF_RE = re.compile(r"^\$\{([a-zA-Z_][\w.\-]*)\}$")
_PARAM_TOKEN_RE = re.compile(r"^\$\{params\.([\w-]+)\}$")
_PARAM_INLINE_RE = re.compile(r"\$\{params\.([\w-]+)\}")


class StepInvocationError(Exception):
    """An input could not be resolved, or failed its runtime version
    recheck. Handled the same as an adapter-reported FAILED result."""


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _flat_step_nodes(flow: list) -> list[StepNode]:
    nodes = []
    for entry in flow:
        if isinstance(entry, StepNode):
            nodes.append(entry)
        else:
            raise NotImplementedError(
                f"'{type(entry).__name__}' flow constructs (splits/deciders/partitioning) "
                "are deferred to E8 — sequential steps only for now"
            )
    return nodes


def _repository_slug(db: Session, repository_id) -> str:
    if not repository_id:
        return "_no-repo"
    repo = db.get(models.Repository, repository_id)
    return repo.slug if repo is not None else "_no-repo"


def _run_base_dir(
    db: Session, instance: models.WfJobInstance, job_execution: models.WfJobExecution
) -> Path:
    """`runs/{engagement_id}/{repository_slug}/{execution_number:04d}-{execution_id_short}`
    — browsable back to the client and repository a run belongs to, unlike a bare
    execution id. Falls back to `_no-repo` when the job declares no
    `repository_id` (or it doesn't resolve to a row) — see 11-STEP-CONTRACT.md."""
    parameters = instance.parameters or {}
    engagement_id = parameters.get("engagement_id") or "_no-engagement"
    repository_slug = _repository_slug(db, parameters.get("repository_id"))
    execution_id_short = str(job_execution.id)[:8]
    execution_dir = f"{job_execution.execution_number:04d}-{execution_id_short}"
    # Absolute: StepContext.working_dir/output_dir are documented as absolute
    # paths (11-STEP-CONTRACT.md), and Path.as_uri() (used when steps report
    # a file:// artifact uri) raises on a relative path. settings.runs_dir
    # defaults to a relative "./runs".
    return (Path(settings.runs_dir) / engagement_id / repository_slug / execution_dir).resolve()


def _resolve_config(value, parameters: dict):
    """Substitutes ${params.x} tokens in a step's `config` block."""
    if isinstance(value, str):
        full = _PARAM_TOKEN_RE.match(value.strip())
        if full:
            return parameters.get(full.group(1))
        return _PARAM_INLINE_RE.sub(lambda m: str(parameters.get(m.group(1), "")), value)
    if isinstance(value, dict):
        return {k: _resolve_config(v, parameters) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_config(v, parameters) for v in value]
    return value


def _resolve_step_output_artifact(
    db: Session, job_execution: models.WfJobExecution, step_name: str, artifact_type: str
) -> models.WfArtifact | None:
    return (
        db.query(models.WfArtifact)
        .join(models.WfStepExecution, models.WfArtifact.step_execution_id == models.WfStepExecution.id)
        .filter(
            models.WfArtifact.job_execution_id == job_execution.id,
            models.WfStepExecution.step_name == step_name,
            models.WfArtifact.artifact_type == artifact_type,
        )
        .order_by(models.WfArtifact.created_at.desc())
        .first()
    )


def _resolve_first_upstream_artifact(
    db: Session, job_execution: models.WfJobExecution, artifact_type: str
) -> models.WfArtifact | None:
    return (
        db.query(models.WfArtifact)
        .filter_by(job_execution_id=job_execution.id, artifact_type=artifact_type)
        .order_by(models.WfArtifact.created_at.asc())
        .first()
    )


def _resolve_external_artifact(
    db: Session, definition: JobDefinitionFile, logical_name: str
) -> models.WfArtifact | None:
    """No external-input provisioning mechanism exists yet in this build —
    nothing supplies one at launch time. Falls back to the most recent
    artifact of the declared type anywhere, as a placeholder until that
    exists. Not exercised by phase0-repository-discovery, which declares no
    external_inputs."""
    external = next(
        (e for e in definition.external_inputs if e.logical_name == logical_name), None
    )
    if external is None:
        return None
    return (
        db.query(models.WfArtifact)
        .filter_by(artifact_type=external.artifact_type)
        .order_by(models.WfArtifact.created_at.desc())
        .first()
    )


def _resolve_inputs(
    db: Session,
    node: StepNode,
    registration: models.WfStepRegistration,
    job_execution: models.WfJobExecution,
    definition: JobDefinitionFile,
) -> dict[str, ArtifactRef]:
    """Resolves each `inputs:` entry to a concrete artifact from wf_artifacts,
    then re-checks its version against the matching `consumes` entry's range
    — the third and final layer of contract-change detection from
    10-ENGINE-CONCEPTS.md, run immediately before invocation."""
    resolved: dict[str, ArtifactRef] = {}
    consumes_by_type = {c["artifact_type"]: c for c in registration.consumes}

    for logical_name, raw_ref in node.inputs.items():
        match = _INPUT_REF_RE.match(raw_ref.strip())
        if not match:
            raise StepInvocationError(
                f"input '{logical_name}' must be a single ${{...}} reference, got {raw_ref!r}"
            )
        parts = match.group(1).split(".")
        kind = parts[0]

        if kind == "external" and len(parts) == 2:
            artifact_row = _resolve_external_artifact(db, definition, parts[1])
        elif kind == "steps" and len(parts) == 4 and parts[2] == "outputs":
            artifact_row = _resolve_step_output_artifact(db, job_execution, parts[1], parts[3])
        elif kind == "artifacts" and len(parts) == 2:
            artifact_row = _resolve_first_upstream_artifact(db, job_execution, parts[1])
        else:
            raise StepInvocationError(f"input '{logical_name}': unsupported reference '{raw_ref}'")

        if artifact_row is None:
            raise StepInvocationError(
                f"input '{logical_name}' ({raw_ref}) did not resolve to an artifact"
            )

        consumes_entry = consumes_by_type.get(artifact_row.artifact_type)
        if consumes_entry and not semver.satisfies(
            artifact_row.artifact_version, consumes_entry["version_range"]
        ):
            raise StepInvocationError(
                f"input '{logical_name}': {artifact_row.artifact_type} "
                f"{artifact_row.artifact_version} no longer satisfies "
                f"{consumes_entry['version_range']} — contract drift since validation"
            )

        resolved[logical_name] = ArtifactRef(
            artifact_type=artifact_row.artifact_type,
            artifact_version=artifact_row.artifact_version,
            uri=artifact_row.uri,
            checksum=artifact_row.checksum,
        )
    return resolved


def _register_artifacts(
    db: Session,
    step_execution: models.WfStepExecution,
    job_execution: models.WfJobExecution,
    outputs: list,
) -> None:
    # Trusts adapter-layer verification (app/workflow/adapters/base.py) — a
    # StepResult with a checksum mismatch would already be FAILED with no
    # outputs by the time it reaches here.
    for output in outputs:
        db.add(
            models.WfArtifact(
                step_execution_id=step_execution.id,
                job_execution_id=job_execution.id,
                artifact_type=output.artifact_type,
                artifact_version=output.artifact_version,
                uri=output.uri,
                checksum=output.checksum,
                artifact_metadata=output.metadata,
            )
        )
    db.flush()


def _resolve_batch_status(exit_status: str, stub_policy: str, on_failure: str) -> tuple[str, bool]:
    """Maps a step's exit_status onto the fixed batch_status vocabulary and
    decides whether the job should halt. Returns (batch_status, should_halt)."""
    if exit_status in ("COMPLETED", "NOOP"):
        return "COMPLETED", False
    if exit_status == "NOT_IMPLEMENTED":
        return ("COMPLETED", False) if stub_policy == "continue" else ("FAILED", True)
    if exit_status == "AWAITING_APPROVAL":
        return "STOPPED", True
    if exit_status == "FAILED":
        return "FAILED", on_failure != "continue"
    # Any other (custom) token is a decider outcome — deciders are deferred
    # to E8, so seeing one here on a plain step is unexpected. Fail loudly
    # (11-STEP-CONTRACT.md's obligations) rather than guess at intent.
    return "FAILED", True


def _carry_forward_step(
    db: Session, job_execution: models.WfJobExecution, prior: models.WfStepExecution
) -> models.WfStepExecution:
    """Copies an already-COMPLETED step (and its artifacts) into the new
    execution unchanged, so this execution's step history is self-contained."""
    new_step_execution = models.WfStepExecution(
        job_execution_id=job_execution.id,
        step_name=prior.step_name,
        step_version=prior.step_version,
        partition_key=prior.partition_key,
        attempt=prior.attempt,
        batch_status=prior.batch_status,
        exit_status=prior.exit_status,
        exit_message=prior.exit_message,
        read_count=prior.read_count,
        write_count=prior.write_count,
        skip_count=prior.skip_count,
        commit_count=prior.commit_count,
        execution_context=prior.execution_context,
        stdout_tail=prior.stdout_tail,
        stderr_tail=prior.stderr_tail,
        started_at=prior.started_at,
        ended_at=prior.ended_at,
    )
    db.add(new_step_execution)
    db.flush()

    for artifact in db.query(models.WfArtifact).filter_by(step_execution_id=prior.id):
        db.add(
            models.WfArtifact(
                step_execution_id=new_step_execution.id,
                job_execution_id=job_execution.id,
                artifact_type=artifact.artifact_type,
                artifact_version=artifact.artifact_version,
                uri=artifact.uri,
                checksum=artifact.checksum,
                size_bytes=artifact.size_bytes,
                artifact_metadata=artifact.artifact_metadata,
            )
        )
    db.flush()
    return new_step_execution


def _max_attempt(db: Session, instance_id, step_name: str) -> int:
    """The highest attempt number ever recorded for this step across every
    execution of this instance — start_limit is enforced against the whole
    instance's history, not just the current execution."""
    result = (
        db.query(func.max(models.WfStepExecution.attempt))
        .join(models.WfJobExecution, models.WfStepExecution.job_execution_id == models.WfJobExecution.id)
        .filter(
            models.WfJobExecution.job_instance_id == instance_id,
            models.WfStepExecution.step_name == step_name,
        )
        .scalar()
    )
    return result or 0


def _invoke_step(
    db: Session,
    job_execution: models.WfJobExecution,
    instance: models.WfJobInstance,
    definition: JobDefinitionFile,
    node: StepNode,
    registration: models.WfStepRegistration,
    attempt: int,
    run_base: Path,
) -> tuple[models.WfStepExecution, StepResult, bool]:
    step_execution = models.WfStepExecution(
        job_execution_id=job_execution.id,
        step_name=node.step,
        step_version=registration.version,
        attempt=attempt,
        batch_status="STARTED",
        started_at=_now(),
    )
    db.add(step_execution)
    db.flush()

    run_root = run_base / node.step
    output_dir = run_root / "out"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        inputs = _resolve_inputs(db, node, registration, job_execution, definition)
    except StepInvocationError as exc:
        step_execution.batch_status = "FAILED"
        step_execution.exit_status = "FAILED"
        step_execution.exit_message = str(exc)
        step_execution.ended_at = _now()
        db.flush()
        return step_execution, StepResult(exit_status="FAILED", exit_message=str(exc)), True

    context = StepContext(
        step_name=node.step,
        step_version=registration.version,
        job_name=definition.job_name,
        job_execution_id=str(job_execution.id),
        step_execution_id=str(step_execution.id),
        attempt=attempt,
        parameters=instance.parameters,
        config=_resolve_config(node.config, instance.parameters),
        inputs=inputs,
        job_context=job_execution.execution_context or {},
        step_context={},
        working_dir=str(run_root),
        output_dir=str(output_dir),
        database_url=settings.database_url,
    )

    adapter = create_adapter(registration.adapter_type, registration.adapter_config)
    try:
        result = adapter.run(context)
    except Exception as exc:
        result = StepResult(
            exit_status="FAILED", exit_message=f"adapter raised {type(exc).__name__}: {exc}"
        )

    batch_status, should_halt = _resolve_batch_status(
        result.exit_status, definition.stub_policy, node.on_failure
    )

    step_execution.batch_status = batch_status
    step_execution.exit_status = result.exit_status
    step_execution.exit_message = result.exit_message
    step_execution.read_count = result.metrics.read_count
    step_execution.write_count = result.metrics.write_count
    step_execution.skip_count = result.metrics.skip_count
    step_execution.commit_count = result.metrics.commit_count
    step_execution.ended_at = _now()

    if result.outputs:
        _register_artifacts(db, step_execution, job_execution, result.outputs)

    if result.job_context_updates:
        job_execution.execution_context = {
            **(job_execution.execution_context or {}),
            **result.job_context_updates,
        }

    db.flush()
    return step_execution, result, should_halt


def run_execution(
    db: Session,
    job_execution: models.WfJobExecution,
    instance: models.WfJobInstance,
    definition: JobDefinitionFile,
) -> models.WfJobExecution:
    """Runs (or resumes) `job_execution` to completion, synchronously — this
    build has no background worker; see 15-REPOSITORY-INGEST-UI.md's
    single-machine operating model. Mutates and returns `job_execution`."""
    flow_steps = _flat_step_nodes(definition.flow)

    prior_execution = (
        db.query(models.WfJobExecution)
        .filter(
            models.WfJobExecution.job_instance_id == instance.id,
            models.WfJobExecution.id != job_execution.id,
        )
        .order_by(models.WfJobExecution.execution_number.desc())
        .first()
    )
    prior_steps_by_name = {}
    if prior_execution is not None:
        prior_steps_by_name = {
            se.step_name: se
            for se in db.query(models.WfStepExecution).filter_by(job_execution_id=prior_execution.id)
        }

    resume_index = len(flow_steps)
    for i, node in enumerate(flow_steps):
        prior = prior_steps_by_name.get(node.step)
        allow_rerun = bool(node.restart and node.restart.allow_start_if_complete)
        if prior is None or prior.batch_status != "COMPLETED" or allow_rerun:
            resume_index = i
            break

    registrations = {
        row.step_name: row
        for row in db.query(models.WfStepRegistration).filter(
            models.WfStepRegistration.step_name.in_([n.step for n in flow_steps])
        )
    }

    job_execution.batch_status = "STARTED"
    job_execution.started_at = _now()
    db.flush()

    run_base = _run_base_dir(db, instance, job_execution)

    for i, node in enumerate(flow_steps):
        if i < resume_index:
            _carry_forward_step(db, job_execution, prior_steps_by_name[node.step])
            continue

        registration = registrations.get(node.step)
        if registration is None:
            job_execution.batch_status = "FAILED"
            job_execution.exit_status = "FAILED"
            job_execution.exit_message = f"step '{node.step}' is not registered"
            job_execution.ended_at = _now()
            db.flush()
            return job_execution

        attempt = _max_attempt(db, instance.id, node.step) + 1
        start_limit = (
            node.restart.start_limit
            if node.restart and node.restart.start_limit is not None
            else DEFAULT_START_LIMIT
        )
        if attempt > start_limit:
            job_execution.batch_status = "ABANDONED"
            job_execution.exit_message = f"step '{node.step}' exceeded start_limit ({start_limit})"
            job_execution.ended_at = _now()
            db.flush()
            return job_execution

        step_execution, result, should_halt = _invoke_step(
            db, job_execution, instance, definition, node, registration, attempt, run_base
        )

        if should_halt:
            job_execution.batch_status = step_execution.batch_status
            job_execution.exit_status = result.exit_status
            job_execution.exit_message = result.exit_message
            job_execution.ended_at = _now()
            db.flush()
            return job_execution

    job_execution.batch_status = "COMPLETED"
    job_execution.exit_status = "COMPLETED"
    job_execution.ended_at = _now()
    db.flush()
    return job_execution
