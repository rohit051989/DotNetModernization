import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AdapterType = Literal["python", "process", "http", "event", "stub"]
ImplementationStatus = Literal["stub", "implemented", "deprecated"]


class ConsumesEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str
    version_range: str
    optional: bool = False


class ProducesEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str
    artifact_version: str


class StepDeclaration(BaseModel):
    """The registration request body — see 11-STEP-CONTRACT.md's 'Step
    declaration'. Registering an already-known step_name updates it in place."""

    step_name: str
    lifecycle_step_no: int | None = None
    display_name: str
    owner_code: str
    version: str
    owner_team: str | None = None
    implementation_status: ImplementationStatus
    consumes: list[ConsumesEntry] = Field(default_factory=list)
    produces: list[ProducesEntry] = Field(default_factory=list)
    adapter_type: AdapterType
    adapter_config: dict[str, Any] = Field(default_factory=dict)


class AffectedConsumer(BaseModel):
    step_name: str
    owner_team: str | None
    consumed_version_range: str


class ContractChangeWarning(BaseModel):
    """A registered step now produces a version of an artifact type that at
    least one existing consumer's declared range cannot accept. See
    10-ENGINE-CONCEPTS.md 'Contract change detection'."""

    artifact_type: str
    new_version: str
    affected_steps: list[AffectedConsumer]


class StepRegistration(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step_name: str
    lifecycle_step_no: int | None
    display_name: str
    owner_code: str
    version: str
    owner_team: str | None
    adapter_type: str
    adapter_config: dict
    consumes: list[dict]
    produces: list[dict]
    implementation_status: str
    registered_at: datetime.datetime
    updated_at: datetime.datetime


class StepRegistrationResult(BaseModel):
    step: StepRegistration
    created: bool
    warnings: list[ContractChangeWarning]
