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


class StepExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(description="This step execution's id.")
    job_execution_id: uuid.UUID = Field(description="The job execution this step ran (or was carried forward) under.")
    step_name: str = Field(description="The step that ran.")
    step_version: str = Field(description="The registered step version at the time of this execution.")
    partition_key: str | None = Field(description="Null for unpartitioned steps — partitioning is deferred to E8.")
    attempt: int = Field(description="Attempt number for this step within this job instance, across all its executions.")
    batch_status: str = Field(description="The engine's own view: STARTING, STARTED, COMPLETED, FAILED, STOPPING, STOPPED, ABANDONED, or UNKNOWN.")
    exit_status: str | None = Field(description="What the step reported: COMPLETED, FAILED, NOOP, AWAITING_APPROVAL, NOT_IMPLEMENTED, or a custom token.")
    exit_message: str | None = Field(description="Human-readable detail about the outcome.")
    read_count: int = Field(description="Chunk metric reported by the step, if any.")
    write_count: int = Field(description="Chunk metric reported by the step, if any.")
    skip_count: int = Field(description="Chunk metric reported by the step, if any.")
    commit_count: int = Field(description="Chunk metric reported by the step, if any.")
    started_at: datetime.datetime | None = Field(description="When this step began. Null for a step carried forward from a prior execution without its original timestamp.")
    ended_at: datetime.datetime | None = Field(description="When this step finished.")


class JobExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(description="This execution's id.")
    job_name: str = Field(description="The job this execution ran, joined from its instance.")
    job_instance_id: uuid.UUID = Field(description="The instance (job name + parameters) this execution belongs to.")
    job_definition_id: uuid.UUID = Field(description="Which stored definition version ran.")
    execution_number: int = Field(description="1, 2, 3... per instance — this instance's Nth attempt.")
    batch_status: str = Field(description="STARTING, STARTED, COMPLETED, FAILED, STOPPING, STOPPED, ABANDONED, or UNKNOWN.")
    exit_status: str | None = Field(description="The terminal exit status for the whole execution, once it has one.")
    exit_message: str | None = Field(description="Human-readable detail about the outcome.")
    execution_context: dict = Field(description="Job-scoped key/value state, shallow-merged from steps' job_context_updates.")
    engine_version: str = Field(description="Version of the runtime that executed this run.")
    triggered_by: str | None = Field(description="'manual', 'api', 'resume', or 'schedule'.")
    started_at: datetime.datetime | None = Field(description="When this execution began.")
    ended_at: datetime.datetime | None = Field(description="When this execution reached a terminal state.")
    created_at: datetime.datetime = Field(description="When this execution row was created.")


class JobExecutionDetail(JobExecutionOut):
    steps: list[StepExecutionOut] = Field(
        default_factory=list,
        description="Every step execution recorded under this execution, including steps carried forward unchanged from a prior execution on restart.",
    )
