import datetime
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LaunchJobRequest(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)


class StepExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_execution_id: uuid.UUID
    step_name: str
    step_version: str
    partition_key: str | None
    attempt: int
    batch_status: str
    exit_status: str | None
    exit_message: str | None
    read_count: int
    write_count: int
    skip_count: int
    commit_count: int
    started_at: datetime.datetime | None
    ended_at: datetime.datetime | None


class JobExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_name: str
    job_instance_id: uuid.UUID
    job_definition_id: uuid.UUID
    execution_number: int
    batch_status: str
    exit_status: str | None
    exit_message: str | None
    execution_context: dict
    engine_version: str
    triggered_by: str | None
    started_at: datetime.datetime | None
    ended_at: datetime.datetime | None
    created_at: datetime.datetime


class JobExecutionDetail(JobExecutionOut):
    steps: list[StepExecutionOut] = Field(default_factory=list)
