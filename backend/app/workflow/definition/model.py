"""Typed model for job definition YAML. See 12-JOB-DEFINITION-FORMAT.md.

A flow entry is a `step`, a `split`, or a `decision` — distinguished by which
key is present, not by an explicit discriminator field, so FlowNode is a
plain union: pydantic's "smart" union mode picks the member that actually
validates (each model uses `extra="forbid"` plus its own required key, so
exactly one ever matches a well-formed entry).
"""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


_WHEN_SOURCE_FIELDS = ("param", "context", "step_status")
_WHEN_OPERATOR_FIELDS = ("eq", "ne", "lt", "lte", "gt", "gte", "in_", "not_in", "exists", "matches")


class WhenLeaf(BaseModel):
    """One condition leaf — 22-STEP-SEQUENCING-AND-POLICY.md Part B grammar.
    Exactly one of `param`/`context`/`step_status` (the value source) and
    exactly one operator. `lt`/`lte`/`gt`/`gte` are declared numeric here —
    whether the *actual* value at evaluation time is comparable is a runtime
    concern (a type mismatch there fails the step; see the evaluator)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    param: str | None = None
    context: str | None = None
    step_status: str | None = None

    eq: Any = None
    ne: Any = None
    lt: float | int | None = None
    lte: float | int | None = None
    gt: float | int | None = None
    gte: float | int | None = None
    in_: list[Any] | None = Field(default=None, alias="in")
    not_in: list[Any] | None = None
    exists: bool | None = None
    matches: str | None = None

    @model_validator(mode="after")
    def _exactly_one_source_and_operator(self) -> "WhenLeaf":
        sources = [f for f in _WHEN_SOURCE_FIELDS if getattr(self, f) is not None]
        if len(sources) != 1:
            raise ValueError(
                "a when: leaf must declare exactly one of param/context/step_status, "
                f"got {sources or 'none'}"
            )
        operators = [f for f in _WHEN_OPERATOR_FIELDS if getattr(self, f) is not None]
        if len(operators) != 1:
            raise ValueError(
                "a when: leaf must declare exactly one operator "
                f"({', '.join(_WHEN_OPERATOR_FIELDS)}), got {operators or 'none'}"
            )
        return self

    @property
    def source_kind(self) -> str:
        """One of 'param', 'context', 'step_status'."""
        return next(f for f in _WHEN_SOURCE_FIELDS if getattr(self, f) is not None)

    @property
    def source_name(self) -> str:
        """The declared name under the source kind, e.g. 'engagement_id'."""
        return getattr(self, self.source_kind)

    @property
    def operator(self) -> tuple[str, Any]:
        """(operator_name, operand) — operator_name is 'in' for the `in_`
        field, matching the YAML key rather than the Python attribute."""
        name = next(f for f in _WHEN_OPERATOR_FIELDS if getattr(self, f) is not None)
        return ("in" if name == "in_" else name), getattr(self, name)

    def describe(self) -> str:
        op_name, operand = self.operator
        return f"{self.source_kind}.{self.source_name} {op_name} {operand!r}"


class WhenAll(BaseModel):
    model_config = ConfigDict(extra="forbid")
    all: list["WhenCondition"]


class WhenAny(BaseModel):
    model_config = ConfigDict(extra="forbid")
    any: list["WhenCondition"]


class WhenNot(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    not_condition: "WhenCondition" = Field(alias="not")


WhenCondition = Union[WhenAll, WhenAny, WhenNot, WhenLeaf]

WhenAll.model_rebuild()
WhenAny.model_rebuild()
WhenNot.model_rebuild()


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
    when: WhenCondition | None = None
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
