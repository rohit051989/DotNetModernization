"""Typed model for job definition YAML. See 12-JOB-DEFINITION-FORMAT.md.

A flow entry is a `step`, a `split`, or a `decision` — distinguished by which
key is present, not by an explicit discriminator field, so FlowNode is a
plain union: pydantic's "smart" union mode picks the member that actually
validates (each model uses `extra="forbid"` plus its own required key, so
exactly one ever matches a well-formed entry).
"""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class ParameterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    required: bool = False
    default: Any = None
    description: str | None = None


class ExternalInputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logical_name: str
    artifact_type: str
    version_range: str
    required: bool = True


class PreconditionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["job_completed", "artifact_exists", "decision_approved"]
    job_name: str | None = None
    scope: str | None = None
    description: str | None = None
    artifact_type: str | None = None
    pattern_id: str | None = None


class PartitionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    partitioner: str
    max_concurrency: int | None = None
    aggregate_outputs: bool = False
    failure_policy: Literal["fail_fast", "continue_on_error"] = "fail_fast"
    max_failed_partitions: int | None = None


class GateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["pull_request", "api"]
    resume_trigger: str | None = None
    tier_condition: str | None = None


class RestartOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_start_if_complete: bool = False
    start_limit: int | None = None


class StepNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: str
    inputs: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    partition: PartitionSpec | None = None
    gate: GateSpec | None = None
    restart: RestartOverride | None = None
    on_failure: Literal["halt", "continue"] = "halt"
    timeout_seconds: int | None = None


class SplitNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    split: str
    max_concurrency: int | None = None
    branches: list[list["FlowNode"]]


class DecisionNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str
    decider: str
    outcomes: dict[str, list["FlowNode"]]
    default: list["FlowNode"] | None = None


FlowNode = Union[StepNode, SplitNode, DecisionNode]

SplitNode.model_rebuild()
DecisionNode.model_rebuild()


class JobDefinitionFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_name: str
    version: int
    description: str | None = None
    parameters: list[ParameterSpec] = Field(default_factory=list)
    external_inputs: list[ExternalInputSpec] = Field(default_factory=list)
    preconditions: list[PreconditionSpec] = Field(default_factory=list)
    stub_policy: Literal["continue", "halt"] = "halt"
    flow: list[FlowNode]
