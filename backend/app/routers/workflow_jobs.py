from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error, errors
from app.workflow.definition import service
from app.workflow.definition.loader import JobDefinitionParseError
from app.workflow.definition.model import JobDefinitionFile
from app.workflow.definition.schemas import (
    JobDefinition,
    JobDefinitionAdminOut,
    JobDefinitionStoreRequest,
    JobDefinitionStoreResult,
    JobDefinitionSummary,
    JobDefinitionValidateRequest,
    JobDefinitionValidateResponse,
    JobDefinitionViewOut,
    JobParameterOut,
    JobParametersResponse,
    ValidationErrorOut,
)
from app.workflow.definition.service import DuplicateJobVersionError
from app.workflow.runtime import service as runtime_service
from app.workflow.runtime.instance import ParameterValidationError
from app.workflow.runtime.schemas import JobExecutionOut, LaunchJobRequest
from app.workflow.runtime.service import PreconditionError

router = APIRouter(prefix="/api/workflow/jobs", tags=["Workflow Jobs"])

_NO_ACTIVE_DEFINITION = {"model": ErrorResponse, "description": "No active definition exists for this job_name."}


def _job_scope(parameter_names: set[str]) -> str:
    if "repository_id" in parameter_names:
        return "per_repository"
    if "engagement_id" in parameter_names:
        return "per_engagement"
    return "other"


@router.get(
    "",
    response_model=list[JobDefinitionSummary],
    summary="List every job with an active definition",
    response_description="One row per registered job — the Workflow tab's jobs list.",
    operation_id="list_job_definitions",
)
def list_job_definitions(db: Session = Depends(get_db)):
    """
    Drives the Workflow tab's jobs panel — job name, active version, scope,
    and how many of its steps are implemented versus stub
    (20-WORKFLOW-OBSERVABILITY-UI.md Part B).
    """
    rows = service.list_active_definitions(db)
    step_names: set[str] = set()
    definitions: dict[str, JobDefinitionFile] = {}
    for row in rows:
        definition = JobDefinitionFile.model_validate(row.definition)
        definitions[row.job_name] = definition
        step_names.update(node.step for node in definition.flow)

    registrations = {
        reg.step_name: reg
        for reg in db.query(models.WfStepRegistration).filter(models.WfStepRegistration.step_name.in_(step_names))
    }

    summaries = []
    for row in rows:
        definition = definitions[row.job_name]
        flow_steps = [node.step for node in definition.flow]
        implemented = sum(
            1 for name in flow_steps if registrations.get(name) and registrations[name].implementation_status == "implemented"
        )
        summaries.append(
            JobDefinitionSummary(
                job_name=row.job_name,
                active_version=row.version,
                description=definition.description,
                scope=_job_scope({p.name for p in definition.parameters}),
                step_count=len(flow_steps),
                implemented_step_count=implemented,
                stub_step_count=len(flow_steps) - implemented,
            )
        )
    return summaries


@router.get(
    "/all-versions",
    response_model=list[JobDefinitionAdminOut],
    summary="List every stored job definition version, active or not, valid or not",
    response_description="One row per stored version — the Workflow Administration tab's Job definitions section.",
    operation_id="list_all_job_definitions",
)
def list_all_job_definitions(db: Session = Depends(get_db)):
    """
    Unlike `GET /api/workflow/jobs` (active-only), this includes every
    stored version of every job — inactive superseded versions and
    definitions that failed validation — so a broken definition is
    discoverable here instead of only via a direct API call
    (23-WORKFLOW-ADMINISTRATION.md Part C2).
    """
    rows = service.list_all_definitions(db)
    step_names: set[str] = set()
    parsed: dict[int, JobDefinitionFile] = {}
    for row in rows:
        definition = JobDefinitionFile.model_validate(row.definition)
        parsed[row.id] = definition
        step_names.update(node.step for node in definition.flow)

    registrations = {
        reg.step_name: reg
        for reg in db.query(models.WfStepRegistration).filter(models.WfStepRegistration.step_name.in_(step_names))
    }
    ids_with_executions = service.definition_ids_with_executions(db, [row.id for row in rows])

    results = []
    for row in rows:
        definition = parsed[row.id]
        flow_steps = [node.step for node in definition.flow]
        implemented = sum(
            1 for name in flow_steps if registrations.get(name) and registrations[name].implementation_status == "implemented"
        )
        results.append(
            JobDefinitionAdminOut(
                job_name=row.job_name,
                version=row.version,
                is_active=row.is_active,
                validation_status=row.validation_status,
                description=definition.description,
                scope=_job_scope({p.name for p in definition.parameters}),
                step_count=len(flow_steps),
                implemented_step_count=implemented,
                has_executions=row.id in ids_with_executions,
            )
        )
    return results


@router.post(
    "/validate",
    response_model=JobDefinitionValidateResponse,
    summary="Validate job definition YAML without storing it",
    response_description="Whether the definition is valid, and every rule violation found.",
    operation_id="validate_job_definition",
    responses={422: {"model": ErrorResponse, "description": "The YAML doesn't parse, or doesn't match the job definition shape at all."}},
)
def validate_job(payload: JobDefinitionValidateRequest, db: Session = Depends(get_db)):
    """
    Runs all 8 static validation rules from 12-JOB-DEFINITION-FORMAT.md and
    reports every violation at once, not just the first — including
    `UNSATISFIED_INPUT`, the contract-change tripwire that checks every
    step's declared `consumes` against upstream `produces` and
    `external_inputs`.
    """
    try:
        definition, errors = service.validate_yaml(db, payload.yaml)
    except JobDefinitionParseError as exc:
        raise error(422, str(exc), code="UNPARSEABLE_YAML") from exc

    return JobDefinitionValidateResponse(
        job_name=definition.job_name,
        version=definition.version,
        validation_status="invalid" if errors else "valid",
        validation_errors=[ValidationErrorOut(**e.to_dict()) for e in errors],
    )


@router.post(
    "",
    response_model=JobDefinitionStoreResult,
    status_code=201,
    summary="Store a job definition version",
    response_description="The stored definition — persisted even when invalid, per 12-JOB-DEFINITION-FORMAT.md.",
    operation_id="store_job_definition",
    responses={
        409: {"model": ErrorResponse, "description": "This job_name + version is already stored."},
        422: {"model": ErrorResponse, "description": "The YAML doesn't parse, or doesn't match the job definition shape at all."},
    },
)
def store_job(payload: JobDefinitionStoreRequest, db: Session = Depends(get_db)):
    """
    Always persists the row, valid or not, so a broken definition can be
    inspected and fixed without losing the attempt. `activate: true` is
    honoured only when validation passes — an invalid definition is never
    activated no matter what this flag says.
    """
    try:
        row, errors = service.store_definition(db, payload.yaml, activate=payload.activate)
    except JobDefinitionParseError as exc:
        raise error(422, str(exc), code="UNPARSEABLE_YAML") from exc
    except DuplicateJobVersionError as exc:
        raise error(409, str(exc), code="DUPLICATE_JOB_VERSION") from exc

    db.commit()
    db.refresh(row)
    return JobDefinitionStoreResult(
        definition=JobDefinition.model_validate(row),
        validation_errors=[ValidationErrorOut(**e.to_dict()) for e in errors],
    )


@router.post(
    "/{job_name}/activate/{version}",
    response_model=JobDefinition,
    summary="Activate a stored, valid job definition version",
    response_description="The now-active definition.",
    operation_id="activate_job_definition",
    responses={
        404: {"model": ErrorResponse, "description": "No definition is stored for this job_name + version."},
        422: {"model": ErrorResponse, "description": "This version's validation_status is not 'valid'."},
    },
)
def activate_job(job_name: str, version: int, db: Session = Depends(get_db)):
    """Deactivates whatever was previously active for this `job_name` (if
    anything) in the same request — at most one active version per job."""
    try:
        row = service.activate_definition(db, job_name, version)
    except LookupError as exc:
        raise error(404, str(exc), code="NOT_FOUND") from exc
    except ValueError as exc:
        raise error(422, str(exc), code="INVALID_DEFINITION") from exc

    db.commit()
    db.refresh(row)
    return JobDefinition.model_validate(row)


@router.get(
    "/{job_name}",
    response_model=JobDefinition,
    summary="Get the active job definition",
    response_description="The currently active definition for this job_name.",
    operation_id="get_active_job_definition",
    responses={404: _NO_ACTIVE_DEFINITION},
)
def get_active_job(job_name: str, db: Session = Depends(get_db)):
    row = service.get_active_definition(db, job_name)
    if row is None:
        raise error(404, f"No active definition for job '{job_name}'", code="NOT_FOUND")
    return JobDefinition.model_validate(row)


@router.get(
    "/{job_name}/versions/{version}",
    response_model=JobDefinition,
    summary="Get one stored job definition version, active or not",
    response_description="That version's stored definition, validation status/errors, and raw YAML.",
    operation_id="get_job_definition_version",
    responses={404: {"model": ErrorResponse, "description": "No definition is stored for this job_name + version."}},
)
def get_job_definition_version(job_name: str, version: int, db: Session = Depends(get_db)):
    """
    Unlike `GET /{job_name}` (active only), this opens any stored version —
    including an inactive or invalid one — for the Workflow Administration
    tab's Job definitions section (23-WORKFLOW-ADMINISTRATION.md Part C2).
    """
    row = service.get_definition_version(db, job_name, version)
    if row is None:
        raise error(404, f"No definition stored for '{job_name}' version {version}", code="NOT_FOUND")
    return JobDefinition.model_validate(row)


@router.delete(
    "/{job_name}/versions/{version}",
    status_code=204,
    summary="Discard a stored job definition version",
    response_description="Deleted. Only ever succeeds for a version that is neither active nor referenced by any execution.",
    operation_id="delete_job_definition_version",
    responses={
        404: {"model": ErrorResponse, "description": "No definition is stored for this job_name + version."},
        409: {
            "model": ErrorResponse,
            "description": "This version is the active definition, or at least one execution still references "
            "it. Either way, discarding is refused — an execution must never be orphaned, and the active "
            "definition must never disappear out from under the engine.",
        },
    },
)
def delete_job_definition_version(job_name: str, version: int, db: Session = Depends(get_db)):
    """
    Permanently removes a stored version — for scaffolding from a
    demonstration or experiment that was stored but never meant to be
    activated (12-JOB-DEFINITION-FORMAT.md: use `POST .../validate` instead,
    which never stores). Refuses with 409 if the version is currently active,
    or if any `wf_job_executions` row references it — an execution's
    `job_definition_id` must never be left dangling.
    """
    try:
        service.delete_definition_version(db, job_name, version)
    except LookupError as exc:
        raise error(404, str(exc), code="NOT_FOUND") from exc
    except service.DefinitionIsActiveError as exc:
        raise error(409, str(exc), code="DEFINITION_IS_ACTIVE") from exc
    except service.DefinitionHasExecutionsError as exc:
        raise error(409, str(exc), code="DEFINITION_HAS_EXECUTIONS") from exc
    db.commit()


@router.get(
    "/{job_name}/parameters",
    response_model=JobParametersResponse,
    summary="Get the launch parameters a job declares",
    response_description="The active definition's declared parameters, with type/required/default/description.",
    operation_id="get_job_parameters",
    responses={404: _NO_ACTIVE_DEFINITION},
)
def get_job_parameters(job_name: str, db: Session = Depends(get_db)):
    """
    Reads the active job definition's `parameters` block — this is how a
    launch form builds its inputs without hardcoding per-job knowledge, and
    the reference every launch validation error points back to.
    """
    row = service.get_active_definition(db, job_name)
    if row is None:
        raise error(404, f"No active definition for job '{job_name}'", code="NOT_FOUND")

    definition = JobDefinitionFile.model_validate(row.definition)
    return JobParametersResponse(
        job_name=job_name,
        definition_version=row.version,
        parameters=[
            JobParameterOut(
                name=p.name,
                type=p.type,
                required=p.required,
                default=p.default,
                description=p.description,
            )
            for p in definition.parameters
        ],
    )


@router.get(
    "/{job_name}/definition",
    response_model=JobDefinitionViewOut,
    summary="Get the active job definition, resolved for display",
    response_description="The active definition's flow, with consumes/produces/inputs wiring, when: prose, and policy state.",
    operation_id="get_job_definition_view",
    responses={404: _NO_ACTIVE_DEFINITION},
)
def get_job_definition_view(
    job_name: str,
    engagement_id: str | None = Query(
        default=None,
        description="When supplied, resolves each step's policy across the engagement and global layers into "
        "policy.source/enabled/reason (23-WORKFLOW-ADMINISTRATION.md Part A). Omit to resolve the global layer "
        "only.",
    ),
    db: Session = Depends(get_db),
):
    """
    Read-only — see 22-STEP-SEQUENCING-AND-POLICY.md Part E. An updater is
    explicitly future work; job definitions stay in git, where reviewable
    change belongs.

    Powers the Workflow tab's job definition viewer: the header counter
    (`implemented_step_count` of `step_count`), the flow cards (consumes,
    produces, `inputs` wiring — the thing that was silently missing for
    step 3 — and `when_description`, a readable prose rendering of `when`),
    and the collapsed raw YAML panel.
    """
    view = service.build_job_definition_view(db, job_name, engagement_id)
    if view is None:
        raise error(404, f"No active definition for job '{job_name}'", code="NOT_FOUND")
    return view


@router.post(
    "/{job_name}/launch",
    response_model=JobExecutionOut,
    status_code=202,
    summary="Launch a job",
    response_description="Accepted. This build runs the job synchronously, so the execution is already terminal by the time this responds.",
    operation_id="launch_job",
    responses={
        404: _NO_ACTIVE_DEFINITION,
        422: {
            "model": ErrorResponse,
            "description": "A parameter was missing, unknown, or the wrong type; a precondition was unmet; or the definition uses a flow construct not yet supported by the runtime (splits/deciders/partitioning).",
        },
    },
)
def launch_job(job_name: str, payload: LaunchJobRequest, db: Session = Depends(get_db)):
    """
    Computes a `job_key` from the canonicalised parameters and resumes the
    matching `wf_job_instances` row if one exists — launching twice with
    identical parameters creates a new **execution** of the same
    **instance**, not a new instance; changing any parameter creates a new
    instance. See `GET /api/workflow/jobs/{job_name}/parameters` for what
    this job accepts.
    """
    try:
        execution = runtime_service.launch_job(db, job_name, payload.parameters, triggered_by="api")
    except LookupError as exc:
        raise error(404, str(exc), code="NOT_FOUND") from exc
    except ParameterValidationError as exc:
        raise errors(422, exc.errors) from exc
    except PreconditionError as exc:
        raise errors(422, exc.failures) from exc
    except NotImplementedError as exc:
        raise error(422, str(exc), code="UNSUPPORTED_FLOW_CONSTRUCT") from exc

    db.commit()
    db.refresh(execution)
    return runtime_service.to_execution_out(db, execution)
