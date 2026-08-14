import datetime
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ValidationErrorOut(BaseModel):
    code: str = Field(description="One of the 8 rule codes from 12-JOB-DEFINITION-FORMAT.md, e.g. 'UNSATISFIED_INPUT'.")
    step: str | None = Field(description="The step this error is about, or null when it isn't about one step.")
    detail: str = Field(description="Human-readable explanation.")
    affected_steps: list[str] = Field(description="Other steps implicated by this error, e.g. consumers broken by a contract change.")


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
