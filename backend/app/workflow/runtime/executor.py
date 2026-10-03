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

Commit per step. Given a `checkpoint` (the session's commit), the engine
commits at every step boundary: when the execution starts, when a step
starts (so a live view shows it running), and when a step ends, with its
row, artifacts and job-context updates. A completed step is therefore
durable the moment it finishes. A crash loses at most the step in flight,
and a resume carries every completed step forward instead of rerunning it —
which matters once steps make changes outside the database, such as git
commits, that a rerun would apply twice. Without a checkpoint (a caller
that wants one transaction, such as a test) the engine only flushes.
"""

import datetime
import re
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.workflow import semver
from app.workflow.adapters import create_adapter
from app.workflow.adapters.base import local_path_from_uri
from app.workflow.contract import ArtifactRef, StepContext, StepResult
from app.workflow.definition.model import JobDefinitionFile, StepNode
from app.workflow.policy import CASCADE_REASON_PREFIX
from app.workflow.runtime.when_eval import WhenEvaluationError, describe_when, evaluate_when

DEFAULT_START_LIMIT = 3
ENGINE_VERSION = "0.1.0"

_INPUT_REF_RE = re.compile(r"^\$\{([a-zA-Z_][\w.\-]*)\}$")
_PARAM_TOKEN_RE = re.compile(r"^\$\{params\.([\w-]+)\}$")
_PARAM_INLINE_RE = re.compile(r"\$\{params\.([\w-]+)\}")
_TIER_CONDITION_RE = re.compile(r"^\s*(\w+)\s*(>=|<=|==|!=|>|<)\s*(.+?)\s*$")


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
) -> tuple[dict[str, ArtifactRef], list[dict]]:
    """Resolves each `inputs:` entry to a concrete artifact from wf_artifacts,
    then re-checks its version against the matching `consumes` entry's range
    — the third and final layer of contract-change detection from
    10-ENGINE-CONCEPTS.md, run immediately before invocation.

    Also returns a persistable `inputs_resolved` record (logical name,
    artifact type/version, artifact id) — the visible evidence, kept on
    `wf_step_executions`, that this step actually received a given upstream
    artifact version (docs/20-WORKFLOW-OBSERVABILITY-UI.md Part A)."""
    resolved: dict[str, ArtifactRef] = {}
    inputs_resolved: list[dict] = []
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
            # `optional: true` on a consumes entry has to mean something at
            # RUNTIME, not only in validation. Rule 9 already lets an
            # optional entry go unwired; this is the other half — wired, but
            # the upstream step produced nothing this run because it was
            # stubbed, skipped by policy, or returned NOOP.
            #
            # Without this, step 6 declaring both its inputs optional
            # (27-STEP-006-PATTERN-VALIDATION.md Part D) still hard-fails
            # the moment step 5 is stubbed, which is exactly the case
            # `optional` exists to survive. The step is invoked with the
            # input simply absent from `inputs` and decides for itself —
            # step 6 returns NOOP.
            #
            # The artifact type is taken from the reference rather than
            # from the (absent) artifact row: `${artifacts.X}` and
            # `${steps.S.outputs.X}` both name X, which is the convention
            # every wiring in this repo follows.
            intended_type = parts[-1]
            if consumes_by_type.get(intended_type, {}).get("optional", False):
                inputs_resolved.append(
                    {
                        "logical_name": logical_name,
                        "artifact_type": intended_type,
                        "artifact_version": None,
                        "artifact_id": None,
                        "resolved": False,
                        "reason": "optional input not produced by this execution",
                    }
                )
                continue
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
        inputs_resolved.append(
            {
                "logical_name": logical_name,
                "artifact_type": artifact_row.artifact_type,
                "artifact_version": artifact_row.artifact_version,
                "artifact_id": str(artifact_row.id),
            }
        )
    return resolved, inputs_resolved


def _register_artifacts(
    db: Session,
    step_execution: models.WfStepExecution,
    job_execution: models.WfJobExecution,
    outputs: list,
) -> None:
    # Trusts adapter-layer verification (app/workflow/adapters/base.py) — a
    # StepResult with a checksum mismatch would already be FAILED with no
    # outputs by the time it reaches here. size_bytes is captured now, while
    # the file is known to exist, so it survives the run directory later
    # being cleaned up (11-STEP-CONTRACT.md / docs/20 Part E).
    for output in outputs:
        try:
            size_bytes = local_path_from_uri(output.uri).stat().st_size
        except OSError:
            size_bytes = None
        db.add(
            models.WfArtifact(
                step_execution_id=step_execution.id,
                job_execution_id=job_execution.id,
                artifact_type=output.artifact_type,
                artifact_version=output.artifact_version,
                uri=output.uri,
                checksum=output.checksum,
                size_bytes=size_bytes,
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


def _tier_condition_satisfied(tier_condition: str, job_context: dict) -> bool:
    """`gate.tier_condition` (12-JOB-DEFINITION-FORMAT.md's "Human gates") is
    a free-form comparison string, e.g. `"tier >= 2"`, evaluated against job
    context — a simpler, older mechanism than the structured `when:`
    grammar, kept as-is here since full gate execution (AWAITING_APPROVAL,
    resume) is not implemented by this engine yet and no current job
    definition declares a gate. If the named key isn't in job context at
    all, the condition is not satisfied (the gate does not yet apply) —
    this predates and is distinct from `when:`'s stricter missing-context
    semantics."""
    match = _TIER_CONDITION_RE.match(tier_condition)
    if not match:
        raise ValueError(f"unrecognised tier_condition syntax: {tier_condition!r}")
    key, op, raw_operand = match.groups()

    actual = job_context.get(key)
    if actual is None:
        return False

    try:
        operand: object = int(raw_operand)
    except ValueError:
        try:
            operand = float(raw_operand)
        except ValueError:
            operand = raw_operand.strip("'\"")

    comparisons = {
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
    }
    try:
        return comparisons[op](actual, operand)
    except TypeError as exc:
        raise ValueError(f"cannot compare {actual!r} {op} {operand!r}: {exc}") from exc


def _evaluate_run_decision(
    node: StepNode,
    job_execution: models.WfJobExecution,
    params: dict,
    step_statuses: dict[str, str],
) -> tuple[str, str | None, str | None]:
    """Precedence per 22-STEP-SEQUENCING-AND-POLICY.md Part B: **policy**,
    then **when:**, then **gate.tier_condition**, then **stub_policy** — the
    first check that resolves to "do not run" wins. `stub_policy` isn't
    decided here: a step only reveals `NOT_IMPLEMENTED` by actually being
    invoked, so it stays in `_resolve_batch_status`, applied after this
    function has already said "run".

    Returns `(decision, skip_reason, message)` where `decision` is one of
    `'run'`, `'skip'`, `'fail'`. Side-effect free — no database access
    beyond what the caller already resolved into `job_execution`."""
    job_context = job_execution.execution_context or {}

    # 1. Policy (global or engagement layer) — read only from the
    # launch-time snapshot, never a live query: "Policy is read once at job
    # launch and snapshotted into the job execution context, so a policy
    # change mid-execution cannot produce a run that half-honoured it"
    # (22-STEP-SEQUENCING-AND-POLICY.md Part C). The snapshot records
    # `source` (23-WORKFLOW-ADMINISTRATION.md Part A) so a disable can be
    # attributed to the right layer even after the fact.
    snapshot = job_context.get("step_policy_snapshot") or {}
    policy_state = snapshot.get(node.step)
    if policy_state is not None and not policy_state.get("enabled", True):
        reason = policy_state.get("reason") or "Disabled by policy"
        if reason.startswith(CASCADE_REASON_PREFIX):
            skip_reason = "CASCADED_POLICY"
        else:
            # Snapshots written before the global layer existed carry no
            # `source` key; every policy row was engagement-scoped then.
            source = policy_state.get("source", "engagement")
            skip_reason = "POLICY_DISABLED_GLOBAL" if source == "global" else "POLICY_DISABLED_ENGAGEMENT"
        return "skip", skip_reason, reason

    # 2. when:
    if node.when is not None:
        try:
            satisfied = evaluate_when(
                node.when, params=params, job_context=job_context, step_statuses=step_statuses
            )
        except WhenEvaluationError as exc:
            return "fail", None, str(exc)
        if not satisfied:
            return "skip", "CONDITION_FALSE", f"when: condition not satisfied: {describe_when(node.when)}"

    # 3. gate.tier_condition
    if node.gate is not None and node.gate.tier_condition:
        try:
            tier_ok = _tier_condition_satisfied(node.gate.tier_condition, job_context)
        except ValueError as exc:
            return "fail", None, f"invalid tier_condition '{node.gate.tier_condition}': {exc}"
        if not tier_ok:
            return "skip", "TIER_NOT_APPLICABLE", f"tier_condition '{node.gate.tier_condition}' not satisfied"

    return "run", None, None


def _record_skip(
    db: Session,
    job_execution: models.WfJobExecution,
    node: StepNode,
    registration: models.WfStepRegistration,
    attempt: int,
    skip_reason: str,
    message: str | None,
) -> models.WfStepExecution:
    """SKIPPED is a success outcome for flow purposes (10-ENGINE-CONCEPTS.md)
    — batch_status COMPLETED — but always gets its own row so the timeline
    never shows an absent step (22-STEP-SEQUENCING-AND-POLICY.md Part D:
    "A skipped step always appears in the timeline. Never omit the row.").
    Produces no artifacts and consumes no inputs."""
    now = _now()
    step_execution = models.WfStepExecution(
        job_execution_id=job_execution.id,
        step_name=node.step,
        step_version=registration.version,
        attempt=attempt,
        batch_status="COMPLETED",
        exit_status="SKIPPED",
        skip_reason=skip_reason,
        exit_message=message,
        started_at=now,
        ended_at=now,
    )
    db.add(step_execution)
    db.flush()
    return step_execution


def _fail_precondition(
    db: Session,
    job_execution: models.WfJobExecution,
    node: StepNode,
    registration: models.WfStepRegistration,
    attempt: int,
    message: str,
    stub_policy: str,
) -> tuple[models.WfStepExecution, bool]:
    """A `when:` evaluation error or an invalid `tier_condition` — a step
    FAILURE, never a skip (Part B: "Fail loud"). Routed through the same
    `_resolve_batch_status` as an adapter-reported failure so `on_failure:
    continue` is honoured identically either way."""
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

    batch_status, should_halt = _resolve_batch_status("FAILED", stub_policy, node.on_failure)
    step_execution.batch_status = batch_status
    step_execution.exit_status = "FAILED"
    step_execution.exit_message = message
    step_execution.ended_at = _now()
    db.flush()
    return step_execution, should_halt


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
        skip_reason=prior.skip_reason,
        read_count=prior.read_count,
        write_count=prior.write_count,
        skip_count=prior.skip_count,
        commit_count=prior.commit_count,
        execution_context=prior.execution_context,
        diagnostics=prior.diagnostics,
        inputs_resolved=prior.inputs_resolved,
        stdout_tail=prior.stdout_tail,
        stderr_tail=prior.stderr_tail,
        carried_forward=True,
        working_dir=prior.working_dir,
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
    commit: Callable[[], None],
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
    # Committed before the step runs: a live view sees it STARTED, and a
    # process step's own database connection can see its execution row.
    commit()

    run_root = run_base / node.step
    output_dir = run_root / "out"
    output_dir.mkdir(parents=True, exist_ok=True)
    step_execution.working_dir = str(run_root)

    try:
        inputs, inputs_resolved = _resolve_inputs(db, node, registration, job_execution, definition)
    except StepInvocationError as exc:
        step_execution.batch_status = "FAILED"
        step_execution.exit_status = "FAILED"
        step_execution.exit_message = str(exc)
        step_execution.ended_at = _now()
        db.flush()
        return step_execution, StepResult(exit_status="FAILED", exit_message=str(exc)), True

    step_execution.inputs_resolved = inputs_resolved or None

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

    adapter = create_adapter(registration.adapter_type, registration.adapter_config, session=db)
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
    step_execution.diagnostics = [d.model_dump() for d in result.diagnostics] or None
    # The process adapter surfaces captured stderr as a PROCESS_STDERR
    # diagnostic (app/workflow/adapters/process_adapter.py) — no adapter
    # currently produces free-form stdout, so stdout_tail stays null
    # (docs/20 Part E: "no output captured" is the normal case).
    step_execution.stderr_tail = next(
        (d.message for d in result.diagnostics if d.code == "PROCESS_STDERR"), None
    )
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
    checkpoint: Callable[[], None] | None = None,
) -> models.WfJobExecution:
    """Runs (or resumes) `job_execution` to completion, synchronously — this
    build has no background worker; see 15-REPOSITORY-INGEST-UI.md's
    single-machine operating model. Mutates and returns `job_execution`.

    `checkpoint` is called at every step boundary (see the module
    docstring); pass the session's commit for per-step durability."""
    flow_steps = _flat_step_nodes(definition.flow)

    def commit() -> None:
        db.flush()
        if checkpoint is not None:
            checkpoint()

    def stopped() -> bool:
        """An operator stop, committed by another session, is honoured at
        the next step boundary — visible only because each step commits."""
        if checkpoint is None:
            return False
        db.refresh(job_execution)
        return job_execution.batch_status == "STOPPED"

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
    commit()

    run_base = _run_base_dir(db, instance, job_execution)

    # step_name -> exit_status recorded so far in *this* execution — the
    # data source for `when:`'s `step_status` leaves. Side-effect free by
    # construction: built up as the loop goes, never re-queried.
    step_statuses: dict[str, str] = {}

    for i, node in enumerate(flow_steps):
        if i < resume_index:
            carried = _carry_forward_step(db, job_execution, prior_steps_by_name[node.step])
            step_statuses[node.step] = carried.exit_status
            commit()
            continue

        if stopped():
            return job_execution

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

        # Precedence per 22-STEP-SEQUENCING-AND-POLICY.md Part B: policy,
        # then when:, then gate.tier_condition — each may skip or fail the
        # step before it is ever invoked. stub_policy remains
        # _resolve_batch_status's concern, reached only via the "run" path.
        decision, skip_reason, message = _evaluate_run_decision(
            node, job_execution, instance.parameters, step_statuses
        )

        if decision == "fail":
            step_execution, should_halt = _fail_precondition(
                db, job_execution, node, registration, attempt, message, definition.stub_policy
            )
            step_statuses[node.step] = "FAILED"
            if should_halt:
                job_execution.batch_status = step_execution.batch_status
                job_execution.exit_status = "FAILED"
                job_execution.exit_message = message
                job_execution.ended_at = _now()
                db.flush()
                return job_execution
            commit()
            continue

        if decision == "skip":
            step_execution = _record_skip(db, job_execution, node, registration, attempt, skip_reason, message)
            step_statuses[node.step] = step_execution.exit_status
            commit()
            continue

        step_execution, result, should_halt = _invoke_step(
            db, job_execution, instance, definition, node, registration, attempt, run_base, commit
        )
        step_statuses[node.step] = result.exit_status
        # The step's row, artifacts and outputs are durable from here on.
        commit()

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
