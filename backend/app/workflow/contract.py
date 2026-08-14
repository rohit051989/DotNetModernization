"""The step envelope — StepContext and StepResult. See 11-STEP-CONTRACT.md.

The envelope is stable: a breaking change requires an envelope_version bump and
a coordinated adapter update. Do not grow these models to carry payload data —
payload lives in `config`, `inputs`/`outputs` artifact refs, and job/step context.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ENVELOPE_VERSION = "1.0"

# Core exit statuses from 10-ENGINE-CONCEPTS.md. Deciders may also return any
# other uppercase token for custom branching, so exit_status is validated as
# "uppercase string" rather than restricted to this list.
CORE_EXIT_STATUSES = (
    "COMPLETED",
    "FAILED",
    "NOOP",
    "AWAITING_APPROVAL",
    "NOT_IMPLEMENTED",
)


class ArtifactRef(BaseModel):
    """A resolved upstream artifact, as it arrives in StepContext.inputs."""

    model_config = ConfigDict(extra="forbid")

    artifact_type: str
    artifact_version: str
    uri: str
    checksum: str


class StepContext(BaseModel):
    """What the engine passes to a step. Steps address `inputs` by logical
    name — never by guessing which upstream step produced them."""

    model_config = ConfigDict(extra="forbid")

    envelope_version: Literal["1.0"] = ENVELOPE_VERSION
    step_name: str
    step_version: str
    job_name: str
    job_execution_id: str
    step_execution_id: str
    attempt: int = 1
    partition_key: str | None = None

    parameters: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, ArtifactRef] = Field(default_factory=dict)

    job_context: dict[str, Any] = Field(default_factory=dict)
    step_context: dict[str, Any] = Field(default_factory=dict)

    working_dir: str
    output_dir: str

    database_url: str | None = None
    log_level: str = "INFO"


class StepOutput(BaseModel):
    """A produced artifact. `checksum` is required — the engine verifies it and
    refuses mismatches."""

    model_config = ConfigDict(extra="forbid")

    artifact_type: str
    artifact_version: str
    uri: str
    checksum: str
    metadata: dict[str, Any] | None = None


class StepMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read_count: int = 0
    write_count: int = 0
    skip_count: int = 0
    commit_count: int = 0


class Diagnostic(BaseModel):
    """A per-item problem that should not halt the whole step — surfaces in the
    UI without failing it."""

    model_config = ConfigDict(extra="forbid")

    level: Literal["info", "warning", "error"]
    code: str
    message: str
    ref: str | None = None


class StepResult(BaseModel):
    """What a step returns. `exit_status` is required; everything else is
    optional. `next` is only honoured for steps declared as deciders."""

    model_config = ConfigDict(extra="forbid")

    envelope_version: Literal["1.0"] = ENVELOPE_VERSION
    exit_status: str
    exit_message: str | None = None

    metrics: StepMetrics = Field(default_factory=StepMetrics)
    outputs: list[StepOutput] = Field(default_factory=list)

    job_context_updates: dict[str, Any] = Field(default_factory=dict)
    step_context_updates: dict[str, Any] = Field(default_factory=dict)

    next: str | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @field_validator("exit_status")
    @classmethod
    def _exit_status_is_uppercase_token(cls, value: str) -> str:
        if not value or not value.isupper():
            raise ValueError(
                f"exit_status must be an uppercase token, got '{value}'"
            )
        return value
