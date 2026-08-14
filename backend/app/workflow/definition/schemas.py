import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ValidationErrorOut(BaseModel):
    code: str
    step: str | None
    detail: str
    affected_steps: list[str]


class JobDefinitionValidateRequest(BaseModel):
    yaml: str


class JobDefinitionValidateResponse(BaseModel):
    job_name: str | None
    version: int | None
    validation_status: Literal["valid", "invalid"]
    validation_errors: list[ValidationErrorOut]


class JobDefinitionStoreRequest(BaseModel):
    yaml: str
    activate: bool = False


class JobDefinition(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_name: str
    version: int
    definition: dict
    checksum: str
    validation_status: str
    validation_errors: list[ValidationErrorOut] | None
    is_active: bool
    created_at: datetime.datetime


class JobDefinitionStoreResult(BaseModel):
    definition: JobDefinition
    validation_errors: list[ValidationErrorOut] = Field(default_factory=list)
