import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AdapterType = Literal["python", "process", "http", "event", "stub"]
ImplementationStatus = Literal["stub", "implemented", "deprecated"]


class ConsumesEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str = Field(description="The artifact type this step needs as input, e.g. 'repository-inventory'.")
    version_range: str = Field(
        description="npm-style semver range the produced version must satisfy: '^1.0.0', '~1.2.0', or '>=1.0.0 <3.0.0'.",
        examples=["^1.0.0"],
    )
    optional: bool = Field(default=False, description="If true, a missing or incompatible producer does not fail validation.")


class ProducesEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str = Field(description="The artifact type this step produces, e.g. 'repository-inventory'.")
    artifact_version: str = Field(description="Concrete semver version of the produced artifact.", examples=["1.0.0"])


class StepDeclaration(BaseModel):
    """The registration request body — see 11-STEP-CONTRACT.md's 'Step
    declaration'. Registering an already-known step_name updates it in place."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "step_name": "repository-ingest",
                    "lifecycle_step_no": 1,
                    "display_name": "Repository estate ingest & inventory creation",
                    "owner_code": "P",
                    "version": "1.0.0",
                    "owner_team": "platform",
                    "implementation_status": "implemented",
                    "consumes": [],
                    "produces": [{"artifact_type": "repository-inventory", "artifact_version": "1.0.0"}],
                    "adapter_type": "python",
                    "adapter_config": {"entrypoint": "app.steps.repository_ingest:run"},
                }
            ]
        }
    )

    step_name: str = Field(description="Fixed slug identifying this step. Do not rename after job definitions reference it.")
    lifecycle_step_no: int | None = Field(default=None, description="1-51, from 17-LIFECYCLE-STEPS.md. Null for helper steps.")
    display_name: str = Field(description="Human-readable step name.")
    owner_code: str = Field(
        description="Who owns this step: 'P' (platform), 'C' (Copilot engine), 'S' (custom skill), 'H' (human), or a combined code like 'P + S'."
    )
    version: str = Field(description="Semver of this step's implementation.")
    owner_team: str | None = Field(default=None, description="Team that built this step, when known.")
    implementation_status: ImplementationStatus = Field(
        description="'stub' (not yet built), 'implemented', or 'deprecated'."
    )
    consumes: list[ConsumesEntry] = Field(
        default_factory=list, description="Artifact types (with version ranges) this step requires as input."
    )
    produces: list[ProducesEntry] = Field(
        default_factory=list, description="Artifact types (with concrete versions) this step produces."
    )
    adapter_type: AdapterType = Field(description="How the engine invokes this step: 'python', 'process', 'http', 'event', or 'stub'.")
    adapter_config: dict[str, Any] = Field(
        default_factory=dict, description="Adapter-specific configuration — shape depends on adapter_type; see 11-STEP-CONTRACT.md."
    )


class AffectedConsumer(BaseModel):
    step_name: str = Field(description="A registered step whose consumes range can no longer accept the new version.")
    owner_team: str | None = Field(description="That step's owner team, so the right people get notified.")
    consumed_version_range: str = Field(description="The range this consumer declared that is now incompatible.")


class ContractChangeWarning(BaseModel):
    """A registered step now produces a version of an artifact type that at
    least one existing consumer's declared range cannot accept. See
    10-ENGINE-CONCEPTS.md 'Contract change detection'."""

    artifact_type: str = Field(description="The artifact type whose produced version changed.")
    new_version: str = Field(description="The newly registered version.")
    affected_steps: list[AffectedConsumer] = Field(description="Every registered step this change may break.")


class StepRegistration(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "step_name": "repository-ingest",
                    "lifecycle_step_no": 1,
                    "display_name": "Repository estate ingest & inventory creation",
                    "owner_code": "P",
                    "version": "0.0.0",
                    "owner_team": None,
                    "adapter_type": "stub",
                    "adapter_config": {"exit_status": "NOT_IMPLEMENTED", "message": "Awaiting implementation by platform team"},
                    "consumes": [],
                    "produces": [],
                    "implementation_status": "stub",
                    "registered_at": "2026-08-14T10:29:29.366121Z",
                    "updated_at": "2026-08-14T10:29:29.366121Z",
                }
            ]
        },
    )

    step_name: str = Field(description="Fixed slug identifying this step.")
    lifecycle_step_no: int | None = Field(description="1-51, from 17-LIFECYCLE-STEPS.md. Null for helper steps.")
    display_name: str = Field(description="Human-readable step name.")
    owner_code: str = Field(description="'P', 'C', 'S', 'H', or a combined code like 'P + S'.")
    version: str = Field(description="Semver of this step's implementation.")
    owner_team: str | None = Field(description="Team that built this step, when known.")
    adapter_type: str = Field(description="How the engine invokes this step.")
    adapter_config: dict = Field(description="Adapter-specific configuration.")
    consumes: list[dict] = Field(description="Artifact types (with version ranges) this step requires as input.")
    produces: list[dict] = Field(description="Artifact types (with concrete versions) this step produces.")
    implementation_status: str = Field(description="'stub', 'implemented', or 'deprecated'.")
    registered_at: datetime.datetime = Field(description="When this step was first registered.")
    updated_at: datetime.datetime = Field(description="When this registration was last updated.")


class StepRegistrationResult(BaseModel):
    step: StepRegistration = Field(description="The registered step, as stored.")
    created: bool = Field(description="True if this call created a new registration; false if it updated an existing one.")
    warnings: list[ContractChangeWarning] = Field(
        description="Contract-change warnings triggered by this registration. Registration always succeeds regardless — these are informational."
    )


class MetricsAvailable(BaseModel):
    """Whether the step that produces each dashboard metric is implemented
    yet. See 15-REPOSITORY-INGEST-UI.md Part G — the frontend renders '—'
    with an explanatory tooltip for anything false here, never a fabricated
    zero."""

    repository_count: bool = Field(description="True once 'repository-ingest' (step 1) is implemented.")
    application_count: bool = Field(description="True once 'application-fingerprinting' (step 3) is implemented.")
    pattern_classification: bool = Field(description="True once 'pattern-classification' (step 4) is implemented.")
    impact_map: bool = Field(description="True once 'impact-map-generation' (step 8) is implemented.")
    test_coverage: bool = Field(description="True once 'test-coverage-assessment' (step 9) is implemented.")
    risk_tier: bool = Field(description="True once 'risk-scoring-tier-assignment' (step 10) is implemented.")


class WorkflowCapabilities(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "implemented_steps": ["repository-ingest"],
                    "metrics_available": {
                        "repository_count": True,
                        "application_count": False,
                        "pattern_classification": False,
                        "impact_map": False,
                        "test_coverage": False,
                        "risk_tier": False,
                    },
                }
            ]
        }
    )

    implemented_steps: list[str] = Field(
        description="step_name of every step with implementation_status: implemented, in lifecycle_step_no order."
    )
    metrics_available: MetricsAvailable = Field(
        description="Derived from wf_step_registrations.implementation_status — never fabricated."
    )
