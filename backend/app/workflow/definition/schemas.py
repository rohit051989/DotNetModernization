import datetime
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.workflow.policy_schemas import StepPolicyOut


class ValidationErrorOut(BaseModel):
    code: str = Field(description="One of the 8 rule codes from 12-JOB-DEFINITION-FORMAT.md, e.g. 'UNSATISFIED_INPUT'.")
    step: str | None = Field(description="The step this error is about, or null when it isn't about one step.")
    detail: str = Field(description="Human-readable explanation.")
    affected_steps: list[str] = Field(description="Other steps implicated by this error, e.g. consumers broken by a contract change.")


class InvalidatedJobDefinition(BaseModel):
    """An active job definition that referenced a step whose registration
    just changed, and is now invalid as a result — see
    22-STEP-SEQUENCING-AND-POLICY.md Part A. Not deactivated; reported so
    the drift is visible at registration time rather than at next launch."""

    job_name: str = Field(description="The job whose active definition became invalid.")
    version: int = Field(description="The now-invalid active definition's version.")
    errors: list[ValidationErrorOut] = Field(description="Every rule violation the re-check found.")


class JobDefinitionValidateRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"yaml": "job_name: example-job\nversion: 1\nflow:\n  - step: repository-ingest\n"}]})

    yaml: str = Field(description="The raw job definition YAML text to validate.")


class JobDefinitionValidateResponse(BaseModel):
    job_name: str | None = Field(description="Parsed job_name, or null if the YAML didn't even parse.")
    version: int | None = Field(description="Parsed version, or null if the YAML didn't even parse.")
    validation_status: Literal["valid", "invalid"] = Field(description="'valid' only when all 8 rules pass.")
    validation_errors: list[ValidationErrorOut] = Field(description="Every rule violation found — all of them, not just the first.")


class JobDefinitionStoreRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "yaml": "job_name: phase0-repository-discovery\nversion: 1\nflow:\n  - step: repository-ingest\n",
                    "activate": True,
                }
            ]
        }
    )

    yaml: str = Field(description="The raw job definition YAML text to store.")
    activate: bool = Field(
        default=False,
        description="Activate this version immediately if it validates. Ignored (never activates) if validation fails.",
    )


class JobDefinition(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(description="This stored definition's id.")
    job_name: str = Field(description="The job this definition is for.")
    version: int = Field(description="Version number, unique per job_name.")
    definition: dict = Field(description="The fully-parsed, defaulted definition — safe to re-validate with JobDefinitionFile.")
    checksum: str = Field(description="SHA-256 of the source YAML text.")
    validation_status: str = Field(description="'valid' or 'invalid'.")
    validation_errors: list[ValidationErrorOut] | None = Field(description="Populated when validation_status is 'invalid'.")
    is_active: bool = Field(description="Whether this is the currently active version for job_name. At most one per job_name.")
    created_at: datetime.datetime = Field(description="When this version was stored.")
    source_yaml: str | None = Field(
        default=None,
        description="The exact YAML text this version was stored from — null for rows stored before this field "
        "existed.",
    )


class JobDefinitionStoreResult(BaseModel):
    definition: JobDefinition = Field(description="The stored definition — persisted even when invalid.")
    validation_errors: list[ValidationErrorOut] = Field(
        default_factory=list, description="Duplicated from definition.validation_errors for convenience."
    )


class JobParameterOut(BaseModel):
    name: str = Field(description="Parameter name, as referenced by ${params.<name>} in the job definition.")
    type: str = Field(description="Declared type, e.g. 'string'.")
    required: bool = Field(description="Whether launch fails if this parameter is omitted and has no default.")
    default: Any = Field(description="Value used when the parameter is omitted, or null if none.")
    description: str | None = Field(description="Human-readable explanation of what this parameter is for, if the job definition provides one.")


class JobDefinitionSummary(BaseModel):
    """One row per registered job for the Workflow tab's jobs list — see
    20-WORKFLOW-OBSERVABILITY-UI.md Part B."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_name": "phase0-repository-discovery",
                    "active_version": 3,
                    "description": "Per-repository discovery and analysis. Lifecycle steps 1,2,3,4,8,9,10.",
                    "scope": "per_repository",
                    "step_count": 7,
                    "implemented_step_count": 2,
                    "stub_step_count": 5,
                }
            ]
        }
    )

    job_name: str
    active_version: int = Field(description="The currently active definition version.")
    description: str | None
    scope: Literal["per_repository", "per_engagement", "other"] = Field(
        description="Derived from declared parameters: 'per_repository' if repository_id is declared, "
        "else 'per_engagement' if engagement_id is declared, else 'other'."
    )
    step_count: int = Field(description="Steps in this definition's flow.")
    implemented_step_count: int = Field(description="Of those, how many are registered with implementation_status 'implemented'.")
    stub_step_count: int = Field(description="Of those, how many are still 'stub'.")


class JobDefinitionAdminOut(BaseModel):
    """One row per **stored version** of every job — not just the active
    one — for the Workflow Administration tab's Job definitions section
    (23-WORKFLOW-ADMINISTRATION.md Part C2: "Include definitions that are
    not active or not valid, clearly marked. A job that failed validation
    should be visible here rather than only discoverable through an API
    call.")."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_name": "phase0-repository-discovery",
                    "version": 4,
                    "is_active": True,
                    "validation_status": "valid",
                    "description": "Per-repository discovery and analysis. Lifecycle steps 1,2,3,4,8,9,10.",
                    "scope": "per_repository",
                    "step_count": 7,
                    "implemented_step_count": 3,
                    "has_executions": True,
                }
            ]
        }
    )

    job_name: str
    version: int
    is_active: bool
    validation_status: Literal["valid", "invalid"]
    description: str | None
    scope: Literal["per_repository", "per_engagement", "other"]
    step_count: int
    implemented_step_count: int
    has_executions: bool = Field(
        description="Whether any wf_job_executions row references this version. A discard is only ever offered "
        "when this is false — an inactive version with no executions has, by construction, never been activated "
        "(executions are only ever created against the active definition at launch)."
    )


class JobParametersResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_name": "phase0-repository-discovery",
                    "definition_version": 1,
                    "parameters": [
                        {
                            "name": "engagement_id",
                            "type": "string",
                            "required": True,
                            "default": None,
                            "description": "The engagement this run belongs to.",
                        },
                        {
                            "name": "repository_id",
                            "type": "string",
                            "required": True,
                            "default": None,
                            "description": "UUID of the registered repository to analyse.",
                        },
                        {
                            "name": "ingest_token",
                            "type": "string",
                            "required": True,
                            "default": None,
                            "description": "UUID generated per registration or rescan. Makes each rescan a distinct job instance rather than a restart of the previous one.",
                        },
                    ],
                }
            ]
        }
    )

    job_name: str = Field(description="The job these parameters belong to.")
    definition_version: int = Field(description="The active definition version these parameters were read from.")
    parameters: list[JobParameterOut] = Field(description="Declared parameters, in definition order.")


class ArtifactRefOut(BaseModel):
    artifact_type: str
    artifact_version: str | None = Field(default=None, description="Null on a consumes entry — that's a range, not a concrete version.")
    version_range: str | None = Field(default=None, description="Only present on a consumes entry.")
    optional: bool | None = Field(default=None, description="Only present on a consumes entry.")


class FlowStepPolicyOut(BaseModel):
    enabled: bool = Field(description="Whether this step runs for the given engagement (or by default, if none was given).")
    source: Literal["default", "global", "engagement"] = Field(
        description="'default' when no policy row applies (absence means enabled); 'global' when only a global "
        "step_policies row applies; 'engagement' when an engagement-layer row overrides it — "
        "23-WORKFLOW-ADMINISTRATION.md Part A: engagement beats global beats default."
    )
    reason: str | None = Field(description="The winning policy row's reason, or null when source is 'default'.")
    global_policy: StepPolicyOut | None = Field(
        description="The global row, if one exists, regardless of which layer won — lets the client view show "
        "inheritance (23-WORKFLOW-ADMINISTRATION.md Part D): an engagement row with source='engagement' but a "
        "disabled global_policy reads 'overrides global disable'."
    )
    engagement_policy: StepPolicyOut | None = Field(
        description="The engagement row, if one exists and an engagement_id was given, regardless of which layer won."
    )


class FlowStepOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "sequence": 3,
                    "step_name": "application-fingerprinting",
                    "lifecycle_step_no": 3,
                    "display_name": "Application fingerprinting",
                    "owner_code": "P + S",
                    "adapter_type": "process",
                    "implementation_status": "implemented",
                    "step_version": "1.0.0",
                    "consumes": [{"artifact_type": "solution-project-inventory", "version_range": "^2.0.0", "optional": False}],
                    "produces": [{"artifact_type": "application-fingerprint", "artifact_version": "1.0.0"}],
                    "inputs": {"solution-project-inventory": "${artifacts.solution-project-inventory}"},
                    "when": None,
                    "when_description": None,
                    "gate": None,
                    "policy": {
                        "enabled": True,
                        "source": "default",
                        "reason": None,
                        "global_policy": None,
                        "engagement_policy": None,
                    },
                }
            ]
        }
    )

    sequence: int = Field(description="1-indexed position in the flow.")
    step_name: str
    lifecycle_step_no: int | None
    display_name: str
    owner_code: str
    adapter_type: str
    implementation_status: str
    step_version: str
    consumes: list[ArtifactRefOut] = Field(description="From the step's registration, not the YAML.")
    produces: list[ArtifactRefOut] = Field(description="From the step's registration, not the YAML.")
    inputs: dict[str, str] = Field(description="Logical name -> source expression, exactly as declared in the flow node.")
    when: dict[str, Any] | None = Field(description="The raw when: condition tree, or null if this step has none.")
    when_description: str | None = Field(
        description="Readable prose rendering of `when`, e.g. "
        "'Runs when test_coverage_percent < 60 and engagement_id ≠ reference-engagement-b'. Null if when is null."
    )
    gate: dict[str, Any] | None = Field(description="The raw gate: spec, or null if this step has none.")
    policy: FlowStepPolicyOut


class JobDefinitionViewOut(BaseModel):
    """Read-only, resolved-for-display view of one job's active definition —
    22-STEP-SEQUENCING-AND-POLICY.md Part E. An updater is explicitly future
    work; definitions stay in git."""

    job_name: str
    version: int
    is_active: bool
    validation_status: str
    description: str | None
    implemented_step_count: int = Field(description="For the header counter, e.g. '1 of 7 steps implemented'.")
    step_count: int
    parameters: list[JobParameterOut]
    flow: list[FlowStepOut]
    raw_yaml: str | None = Field(
        description="The exact YAML this version was stored from, for the collapsed 'Raw YAML' panel. "
        "Null only for a version stored before this field existed."
    )
