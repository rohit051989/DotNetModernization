import datetime
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LaunchJobRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "parameters": {
                        "engagement_id": "client-a-ocp4",
                        "repository_id": "3f2b8c14-9d7e-4a51-b6c2-8e1d4f70a9b3",
                        "ingest_token": "c81d4e2f-6a3b-4f19-9c7d-2e5a8b1f30c6",
                    }
                }
            ]
        }
    )

    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Values for this job's declared parameters. Shape varies per job — "
            "see GET /api/workflow/jobs/{job_name}/parameters before launching."
        ),
    )


class DiagnosticOut(BaseModel):
    level: str = Field(description="'info', 'warning', or 'error'.")
    code: str = Field(description="Short machine-readable slug.")
    message: str = Field(description="Human-readable detail.")
    ref: str | None = Field(default=None, description="Optional pointer to the item this diagnostic is about — a file path, artifact type, etc.")


class ResolvedInputRef(BaseModel):
    """One entry from a step's `inputs:` mapping, resolved to a concrete
    artifact — the visible evidence the contract machinery worked (docs/20
    Part A): 'you can see step 2 received step 1's artifact, and which
    version.'"""

    logical_name: str = Field(description="The key this step's job-flow `inputs:` mapping used to address the artifact.")
    artifact_type: str
    # Null when `resolved` is false — an input declared `optional: true` on
    # the step registration whose producer did not run this execution.
    # Recording the miss is the point: "we looked for it and it was not
    # there" is exactly the evidence docs/20 Part A wants visible, and is
    # very different from the input never having been wired.
    artifact_version: str | None = None
    artifact_id: uuid.UUID | None = Field(default=None, description="Links to GET /api/workflow/artifacts/{artifact_id}. Null for an unresolved optional input.")
    resolved: bool = Field(default=True, description="False when an optional input had no artifact to bind to.")
    reason: str | None = Field(default=None, description="Why an optional input went unresolved.")


class ProducedOutputRef(BaseModel):
    artifact_id: uuid.UUID
    artifact_type: str
    artifact_version: str


class StepExecutionOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "step_execution_id": "8f2c1b4a-9d7e-4a51-b6c2-8e1d4f70a9b3",
                    "step_name": "repository-ingest",
                    "lifecycle_step_no": 1,
                    "display_name": "Repository estate ingest & inventory creation",
                    "owner_code": "P",
                    "step_version": "1.0.0",
                    "adapter_type": "python",
                    "implementation_status": "implemented",
                    "sequence": 1,
                    "attempt": 1,
                    "batch_status": "COMPLETED",
                    "exit_status": "COMPLETED",
                    "exit_message": "Ingested repository 'order-management' (clone URL verified)",
                    "metrics": {"read_count": 1, "write_count": 1, "skip_count": 0, "commit_count": 1},
                    "started_at": "2026-08-05T12:00:00Z",
                    "ended_at": "2026-08-05T12:00:03Z",
                    "duration_seconds": 3.104,
                    "diagnostics": [],
                    "inputs_resolved": [],
                    "outputs_produced": [
                        {
                            "artifact_id": "9c2e6f1a-1234-4a51-b6c2-8e1d4f70a9b3",
                            "artifact_type": "repository-inventory",
                            "artifact_version": "1.1.0",
                        }
                    ],
                    "stdout_tail": None,
                    "stderr_tail": None,
                    "working_dir": "runs/client-a-ocp4/order-management/0002-8f2c1b4a/repository-ingest",
                    "carried_forward": False,
                }
            ]
        }
    )

    step_execution_id: uuid.UUID = Field(description="This step execution's id.")
    job_execution_id: uuid.UUID = Field(description="The job execution this step ran (or was carried forward) under.")
    step_name: str = Field(description="The step that ran.")
    lifecycle_step_no: int | None = Field(description="1-51, from 17-LIFECYCLE-STEPS.md. Joined from wf_step_registrations.")
    display_name: str = Field(description="Human-readable step name, joined from wf_step_registrations.")
    owner_code: str = Field(description="'P', 'C', 'S', 'H', or a combined code, joined from wf_step_registrations.")
    step_version: str = Field(description="The registered step version at the time of this execution.")
    adapter_type: str = Field(description="How the engine invoked this step, joined from wf_step_registrations.")
    implementation_status: str = Field(description="'stub', 'implemented', or 'deprecated', joined from wf_step_registrations.")
    sequence: int = Field(description="1-based position of this step in the job's flow order.")
    partition_key: str | None = Field(description="Null for unpartitioned steps — partitioning is deferred to E8.")
    attempt: int = Field(description="Attempt number for this step within this job instance, across all its executions.")
    batch_status: str = Field(description="The engine's own view: STARTING, STARTED, COMPLETED, FAILED, STOPPING, STOPPED, ABANDONED, or UNKNOWN.")
    exit_status: str | None = Field(description="What the step reported: COMPLETED, FAILED, NOOP, AWAITING_APPROVAL, NOT_IMPLEMENTED, SKIPPED, or a custom token.")
    exit_message: str | None = Field(description="Human-readable detail about the outcome.")
    skip_reason: str | None = Field(
        description="Populated only when exit_status is SKIPPED: POLICY_DISABLED, CONDITION_FALSE, "
        "TIER_NOT_APPLICABLE, UPSTREAM_SKIPPED, or CASCADED_POLICY — see 22-STEP-SEQUENCING-AND-POLICY.md Part D."
    )
    metrics: dict[str, int] = Field(description="read_count, write_count, skip_count, commit_count.")
    started_at: datetime.datetime | None = Field(description="When this step began. Null for a step carried forward from a prior execution without its original timestamp.")
    ended_at: datetime.datetime | None = Field(description="When this step finished.")
    duration_seconds: float | None = Field(description="ended_at minus started_at, in seconds. Null until both are set.")
    diagnostics: list[DiagnosticOut] = Field(default_factory=list, description="Per-item problems reported by the step, e.g. captured stderr.")
    inputs_resolved: list[ResolvedInputRef] = Field(default_factory=list, description="Every artifact this step's `inputs:` mapping resolved to, with the version actually received.")
    outputs_produced: list[ProducedOutputRef] = Field(default_factory=list, description="Every artifact this step registered.")
    stdout_tail: str | None = Field(description="Last 8KB of captured stdout. Null — 'no output captured' — is normal, not an error.")
    stderr_tail: str | None = Field(description="Last 8KB of captured stderr. Null — 'no output captured' — is normal, not an error.")
    working_dir: str | None = Field(description="This step's working directory on disk.")
    carried_forward: bool = Field(description="True when this row was copied unchanged from a prior execution on restart, rather than re-run.")
    progress: dict | None = Field(default=None, description="rbc-release-5: what the step last reported — phase, done, total, "
                                   "item, elapsedSeconds — while it runs, and where it was when it ended. Null for a step "
                                   "that reported nothing.")
    progress_at: datetime.datetime | None = Field(default=None, description="When the step last reported progress.")


class StepSummary(BaseModel):
    total: int = Field(description="Steps declared in the job's flow.")
    completed: int = Field(description="Steps whose exit_status is COMPLETED.")
    not_implemented: int = Field(description="Steps whose exit_status is NOT_IMPLEMENTED.")
    skipped: int = Field(
        description="Steps whose exit_status is SKIPPED — see skip_reason on each step for why "
        "(POLICY_DISABLED, CONDITION_FALSE, TIER_NOT_APPLICABLE, UPSTREAM_SKIPPED, CASCADED_POLICY)."
    )
    failed: int = Field(description="Steps whose batch_status is FAILED.")
    pending: int = Field(description="Steps not yet reached by this execution.")


class JobExecutionOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "9c2e6f1a-1234-4a51-b6c2-8e1d4f70a9b3",
                    "job_name": "phase0-repository-discovery",
                    "job_instance_id": "3f2b8c14-9d7e-4a51-b6c2-8e1d4f70a9b3",
                    "job_definition_id": "42133eec-55a0-4909-a221-d8fbd672d6a5",
                    "job_definition_version": 3,
                    "execution_number": 2,
                    "batch_status": "COMPLETED",
                    "exit_status": "COMPLETED",
                    "exit_message": None,
                    "execution_context": {},
                    "engine_version": "0.1.0",
                    "triggered_by": "api",
                    "started_at": "2026-08-05T12:00:00Z",
                    "ended_at": "2026-08-05T12:00:04Z",
                    "duration_seconds": 4.812,
                    "created_at": "2026-08-05T12:00:00Z",
                    "resolved_context": {
                        "engagement_name": "Client A",
                        "repository_slug": "order-management",
                        "repository_name": "Order Management",
                    },
                    "step_summary": {"total": 7, "completed": 1, "not_implemented": 6, "failed": 0, "pending": 0},
                    "artifact_count": 1,
                    "can_restart": False,
                    "can_resume": False,
                }
            ]
        }
    )

    id: uuid.UUID = Field(description="This execution's id.")
    job_name: str = Field(description="The job this execution ran, joined from its instance.")
    job_instance_id: uuid.UUID = Field(description="The instance (job name + parameters) this execution belongs to.")
    job_definition_id: uuid.UUID = Field(description="Which stored definition version ran.")
    job_definition_version: int = Field(description="The definition's own version number, joined from wf_job_definitions.")
    execution_number: int = Field(description="1, 2, 3... per instance — this instance's Nth attempt.")
    batch_status: str = Field(description="STARTING, STARTED, COMPLETED, FAILED, STOPPING, STOPPED, ABANDONED, or UNKNOWN.")
    exit_status: str | None = Field(description="The terminal exit status for the whole execution, once it has one.")
    exit_message: str | None = Field(description="Human-readable detail about the outcome.")
    execution_context: dict = Field(description="Job-scoped key/value state, shallow-merged from steps' job_context_updates.")
    parameters: dict[str, Any] = Field(description="This instance's launch parameters, joined from wf_job_instances.")
    engine_version: str = Field(description="Version of the runtime that executed this run.")
    triggered_by: str | None = Field(description="'manual', 'api', 'resume', or 'schedule'.")
    started_at: datetime.datetime | None = Field(description="When this execution began.")
    ended_at: datetime.datetime | None = Field(description="When this execution reached a terminal state.")
    duration_seconds: float | None = Field(description="ended_at minus started_at, in seconds. Null until both are set.")
    created_at: datetime.datetime = Field(description="When this execution row was created.")
    resolved_context: dict[str, str] = Field(
        description="Opaque instance parameters resolved to names — e.g. engagement_name, repository_slug, "
        "repository_name — so the UI never shows a bare UUID. Keys that don't apply to this job are omitted, not null."
    )
    step_summary: StepSummary = Field(description="Roll-up of this execution's step outcomes.")
    artifact_count: int = Field(description="Artifacts registered by any step under this execution.")
    can_restart: bool = Field(description="True when batch_status is FAILED — POST .../resume creates a new execution that carries forward completed steps.")
    can_resume: bool = Field(description="True when batch_status is STOPPED — POST .../resume continues past a gate or manual stop.")


class JobExecutionDetail(JobExecutionOut):
    steps: list[StepExecutionOut] = Field(
        default_factory=list,
        description="Every step execution recorded under this execution, including steps carried forward unchanged from a prior execution on restart.",
    )


class ArtifactSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(description="This artifact's id.")
    artifact_type: str
    artifact_version: str
    size_bytes: int | None = Field(description="Captured when the step registered it. Null if the file could not be stat'd at that time.")
    checksum: str = Field(description="sha256:<hex>, as declared by the producing step.")
    step_name: str = Field(description="The step that produced this artifact.")
    step_execution_id: uuid.UUID = Field(description="The specific step execution that produced this artifact.")
    created_at: datetime.datetime = Field(description="When this artifact was registered.")


class ArtifactDetail(ArtifactSummary):
    job_execution_id: uuid.UUID = Field(description="The execution this artifact was produced under.")
    uri: str = Field(description="The artifact's file:// URI, as recorded by the producing step.")
    resolved_path: str | None = Field(description="Local filesystem path resolved from uri. Null if the URI scheme is unsupported.")
    file_exists: bool = Field(description="Whether the file currently exists on disk. False does not mean the record is wrong — run directories can be cleaned up.")
    metadata: dict[str, Any] | None = Field(description="Step-reported metadata not part of the hashed file content, e.g. generated_at.")
