import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StepPolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    engagement_id: str
    step_name: str
    enabled: bool
    reason: str | None = Field(description="Null unless this row records a disablement or an explicit note.")
    set_by: str | None = Field(description="Operator name — free text until auth exists.")
    set_at: datetime.datetime
    created_at: datetime.datetime
    updated_at: datetime.datetime


class StepPolicyRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "step_name": "application-fingerprinting",
                    "enabled": False,
                    "reason": "Client already has an internal fingerprinting process for this estate.",
                    "set_by": "jane.doe",
                }
            ]
        }
    )

    step_name: str = Field(description="A registered step, e.g. 'application-fingerprinting'.")
    enabled: bool = Field(description="False to disable this step for the engagement; true to (re-)enable it.")
    reason: str | None = Field(
        default=None,
        description="Required when enabled is false — surfaces in the timeline and the policy summary strip.",
    )
    set_by: str | None = Field(default=None, description="Operator name. Free text until auth exists.")
    cascade: bool = Field(
        default=False,
        description="When disabling would orphan a dependent step's required input, set true to also disable "
        "every named dependent in the same request, each recorded with reason "
        "'cascaded from disabling <step_name>'. Ignored when enabled is true.",
    )

    @model_validator(mode="after")
    def _reason_required_when_disabling(self) -> "StepPolicyRequest":
        if not self.enabled and not (self.reason and self.reason.strip()):
            raise ValueError("reason is required when enabled is false")
        return self


class StepPolicySetResult(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "policy": {
                        "id": "8f2c1a3b-0000-4000-8000-000000000010",
                        "engagement_id": "client-a-ocp4",
                        "step_name": "solution-discovery",
                        "enabled": False,
                        "reason": "Client rescoping — discovery already run manually.",
                        "set_by": "jane.doe",
                        "set_at": "2026-08-19T12:00:00Z",
                        "created_at": "2026-08-19T12:00:00Z",
                        "updated_at": "2026-08-19T12:00:00Z",
                    },
                    "cascaded": [
                        {
                            "id": "8f2c1a3b-0000-4000-8000-000000000011",
                            "engagement_id": "client-a-ocp4",
                            "step_name": "application-fingerprinting",
                            "enabled": False,
                            "reason": "cascaded from disabling solution-discovery",
                            "set_by": "jane.doe",
                            "set_at": "2026-08-19T12:00:00Z",
                            "created_at": "2026-08-19T12:00:00Z",
                            "updated_at": "2026-08-19T12:00:00Z",
                        }
                    ],
                }
            ]
        }
    )

    policy: StepPolicyOut = Field(description="The policy row for the requested step_name.")
    cascaded: list[StepPolicyOut] = Field(
        default_factory=list,
        description="Additional policy rows created because cascade: true was set. Empty otherwise.",
    )


class PolicyOrphanDetail(BaseModel):
    code: Literal["POLICY_ORPHANS_DEPENDENTS"] = "POLICY_ORPHANS_DEPENDENTS"
    message: str = Field(description="Human-readable explanation naming the dependent step(s).")
    dependent_steps: list[str] = Field(description="Steps that would lose a required input if this disable proceeded.")
    resolution: str = Field(description="What the caller can do: retry with cascade: true, or leave the step enabled.")


class PolicyOrphansDependentsResponse(BaseModel):
    """409 body shape for the dependency guard —
    22-STEP-SEQUENCING-AND-POLICY.md Part C. Deliberately not the generic
    field/message/code ErrorResponse: this conflict spans several steps, not
    one field, and the caller needs the dependent list and a concrete next
    action, not just a message."""

    detail: list[PolicyOrphanDetail]


class PolicyRevertOrphanDetail(BaseModel):
    code: Literal["POLICY_REVERT_ORPHANS_STEP"] = "POLICY_REVERT_ORPHANS_STEP"
    message: str = Field(description="Human-readable explanation naming the still-disabled blocking step(s).")
    blocking_steps: list[str] = Field(
        description="Steps this one depends on for a required input, still disabled by policy."
    )
    resolution: str = Field(
        description="Re-enable the blocking step(s) first, or retry with ?force=true to accept the orphaned state."
    )


class PolicyRevertOrphansResponse(BaseModel):
    """409 body shape for DELETE's re-enable guard — the mirror image of
    `PolicyOrphansDependentsResponse`, for when reverting a policy (deleting
    a disabled row) would re-enable a step whose required input's producer
    is still disabled."""

    detail: list[PolicyRevertOrphanDetail]


class StepPolicyValidateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"step_name": "solution-discovery", "enabled": False}]}
    )

    step_name: str = Field(description="A registered step, e.g. 'solution-discovery'.")
    enabled: bool = Field(
        default=False,
        description="The change being considered. Only enabled: false can orphan anything — enabling never does.",
    )


class StepPolicyValidateResponse(BaseModel):
    would_orphan: bool = Field(description="True if this change, applied without cascade, would be refused with 409.")
    dependent_steps: list[str] = Field(
        description="Steps that would lose a required input. Empty when would_orphan is false."
    )
    message: str | None = Field(description="Human-readable summary, or null when would_orphan is false.")
