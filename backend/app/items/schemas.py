"""Request and response shapes for the item catalog —
28-ITEM-AND-CONVERSION-MODEL.md Parts C to H.

Readiness (`state`, `state_reason`) appears only on response models. Every
request model forbids extra fields, so a caller trying to set readiness gets
a 422 rather than a silently ignored field.
"""

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app import models
from app.items.detection import ItemScope
from app.schemas import ConsumerImpact, EffortLevel, ForcingPerspective, _validate_slug

ReadinessState = Literal["ready", "not_ready"]
ExtractorStatus = Literal["implemented", "planned"]
ItemCategory = Literal[
    "hosting",
    "logging",
    "configuration",
    "security",
    "data-access",
    "integration",
    "packaging",
    "dependencies",
    "framework",
]
ItemStatus = Literal["active", "deprecated"]
# Part D "Project role is computed, not catalogued" — the values step 6
# derives. An item lists the roles it never applies to.
ProjectRole = Literal["TEST", "DEPLOYMENT", "DATABASE", "APPLICATION", "LIBRARY", "UNKNOWN"]
EngagementDecisionStatus = Literal["pending", "in_review", "approved", "superseded"]

_COMPUTED_FIELDS = ("state", "state_reason")


def _reject_computed(data):
    """Clearer than pydantic's generic 'extra inputs are not permitted'."""
    if isinstance(data, dict):
        present = [name for name in _COMPUTED_FIELDS if name in data]
        if present:
            raise ValueError(
                f"{', '.join(present)} is computed from signal readiness and cannot be set; "
                "change the detection, or the signals and extractors it depends on."
            )
    return data


# ---------- readiness propagation ----------


class StateChange(BaseModel):
    signal: str | None = Field(default=None, description="Set for a signal state change.")
    item_id: str | None = Field(default=None, description="Set for an item state change.")
    from_: str = Field(alias="from", serialization_alias="from")
    to: str

    model_config = ConfigDict(populate_by_name=True)


class Propagation(BaseModel):
    """What a write changed, downstream. An item listed in `items_changed`
    moved because a signal it depends on did — nobody edited it."""

    signals_changed: list[StateChange] = Field(description="Signals whose state changed in this write.")
    items_changed: list[StateChange] = Field(description="Items whose state changed as a result.")


# ---------- extractors ----------


class ExtractorDeclaration(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "description": "Serilog sink configuration in appsettings*.json.",
                    "status": "planned",
                    "emits": ["SERILOG_FILE_SINK_CONFIG"],
                    "owner_team": "platform",
                }
            ]
        },
    )

    description: str | None = Field(default=None)
    status: ExtractorStatus = Field(
        description="'implemented' makes every signal it declares ready; 'planned' declares them ahead of the code."
    )
    emits: list[str] = Field(
        default_factory=list,
        description="Every signal this extractor emits today (or will, for a planned extractor).",
    )
    planned_emits: list[str] = Field(
        default_factory=list,
        description="Signals an implemented extractor will gain but does not emit yet: claimed, not ready. "
        "Move a name to `emits` when its extraction code ships.",
    )
    owner_team: str | None = Field(default=None)

    @model_validator(mode="after")
    def _disjoint(self) -> "ExtractorDeclaration":
        overlap = sorted(set(self.emits) & set(self.planned_emits))
        if overlap:
            raise ValueError(f"A signal is either emitted or planned, not both: {', '.join(overlap)}")
        return self


class ExtractorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None
    status: ExtractorStatus
    emits: list[str]
    planned_emits: list[str]
    owner_team: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExtractorWriteResult(BaseModel):
    extractor: ExtractorOut
    created: bool
    propagation: Propagation


# ---------- signals ----------


class SignalRegistration(BaseModel):
    """Registers a signal ahead of its registry file — typically alongside a
    `planned` extractor declaring it. The expected extractor must already
    list it in `emits`; otherwise the signal would be unclaimed (hard error)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="SCREAMING_SNAKE_CASE signal name.")
    category: str = Field(description="One of the sixteen step 3 categories (21-STEP-003-FINGERPRINTING.md Part D).")
    type: str = Field(
        description="One of the step 3 signal types, including API_INVOCATION and LITERAL (Part D 'Signal types')."
    )
    description: str | None = None
    extractor: str = Field(description="The extractor expected to emit it (the registry file's `extractor` field).")
    evidence_kind: Literal["FILE", "FOLDER", "NONE"]
    value_semantics: str | None = None
    signal_introduced_in_version: str = Field(
        description="The signal registry version this signal will ship in, e.g. '1.4.0'.",
        pattern=r"^\d+\.\d+\.\d+$",
    )

    @model_validator(mode="before")
    @classmethod
    def _no_computed_fields(cls, data):
        return _reject_computed(data)

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        if value not in models.SIGNAL_CATEGORY:
            raise ValueError(f"'{value}' is not a step 3 signal category")
        return value

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in models.SIGNAL_TYPE:
            raise ValueError(f"'{value}' is not a step 3 signal type")
        return value


class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    category: str
    type: str
    description: str | None
    expected_extractor: str
    evidence_kind: str
    value_semantics: str | None
    signal_introduced_in_version: str
    state: ReadinessState
    state_reason: dict | None
    updated_at: datetime.datetime


class SignalWriteResult(BaseModel):
    signal: SignalOut
    created: bool
    propagation: Propagation


class RegistrySyncResult(BaseModel):
    registry_version: str
    signals_in_registry: int
    signals_anticipated: int = Field(description="Signals registered ahead of step 3 from anticipated_signals.yaml.")
    signals_created: int
    extractors: int
    signals_changed: list[StateChange]
    items_changed: list[StateChange]


# ---------- catalog items ----------


class CatalogItemWrite(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "Serilog file sink writing to a Windows path",
                    "scope": "occurrence",
                    "category": "logging",
                    "detection": {
                        "match": {"all": [{"id": "has-file-sink", "signal": {"name": "SERILOG_FILE_SINK_CONFIG"}}]},
                        "occurrence_source": {"signal": "SERILOG_FILE_SINK_CONFIG", "group_by": "source_path"},
                    },
                    "excluded_roles": ["TEST"],
                }
            ]
        },
    )

    name: str
    description: str | None = None
    scope: ItemScope = Field(
        description="'application': at most once per project, a choice about the project. "
        "'occurrence': can occur many times in one project; located by occurrence_source."
    )
    category: ItemCategory
    detection: dict = Field(description="`match` plus, for occurrence scope, `occurrence_source` (Part E).")
    excluded_roles: list[ProjectRole] = Field(default_factory=list, description="Project roles this item never applies to.")
    owner_team: str | None = None
    status: ItemStatus = Field(default="active", description="Lifecycle status. Distinct from computed readiness.")

    @model_validator(mode="before")
    @classmethod
    def _no_computed_fields(cls, data):
        return _reject_computed(data)


class CatalogItemCreate(CatalogItemWrite):
    id: str = Field(description="Slug, e.g. 'serilog-file-sink'.")

    @field_validator("id")
    @classmethod
    def _slug(cls, value: str) -> str:
        return _validate_slug(value)


class CatalogItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    scope: ItemScope
    category: str
    detection: dict
    excluded_roles: list[str]
    state: ReadinessState = Field(description="Computed. Only 'ready' items are evaluated by detection.")
    state_reason: dict | None = Field(description="Computed. Null when ready.")
    version: int = Field(description="Bumped whenever detection changes.")
    owner_team: str | None
    status: ItemStatus
    deleted_at: datetime.datetime | None
    deleted_by: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class CatalogItemWriteResult(BaseModel):
    item: CatalogItemOut
    warnings: list[str] = Field(description="Non-blocking, e.g. signals referenced but not yet registered.")


class SoftDeleteResponse(BaseModel):
    id: str
    deleted_at: datetime.datetime | None


# ---------- resolutions ----------


class ResolutionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    target_description: str | None = None
    consumer_impact: ConsumerImpact
    effort: EffortLevel
    is_default: bool = Field(default=False, description="At most one default per item.")
    linux_compatible: bool = True
    container_ready: bool = True
    notes: str | None = None
    status: ItemStatus = "active"


class ResolutionCreate(ResolutionWrite):
    id: str = Field(description="Slug, e.g. 'console-json-only'.")

    @field_validator("id")
    @classmethod
    def _slug(cls, value: str) -> str:
        return _validate_slug(value)


class ResolutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    item_id: str
    name: str
    description: str | None
    target_description: str | None
    consumer_impact: ConsumerImpact
    effort: EffortLevel
    is_default: bool
    linux_compatible: bool
    container_ready: bool
    notes: str | None
    status: ItemStatus
    deleted_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


# ---------- engagement decisions ----------


class EngagementDecisionUpsert(BaseModel):
    """Partial-update semantics on an existing decision: an omitted field
    keeps its current value."""

    model_config = ConfigDict(extra="forbid")

    resolution_id: str | None = None
    candidates_considered: list[str] | None = Field(
        default=None, description="Resolution ids presented at decision time. History only; validation uses the full menu."
    )
    rationale: str | None = None
    forcing_perspective: ForcingPerspective | None = None
    forcing_rationale: str | None = Field(
        default=None, description="Why the forcing perspective overrides the lowest-impact option. Paired with forcing_perspective."
    )
    evaluation_notes: str | None = None
    approver_name: str | None = None
    approver_role: str | None = None
    decision_date: datetime.date | None = None
    status: Literal["pending", "in_review", "approved"] | None = Field(
        default=None, description="Use the supersede endpoint to supersede. Defaults to 'pending' on create."
    )


class EngagementDecisionOut(BaseModel):
    id: str
    engagement_id: str
    item_id: str
    item_name: str
    resolution_id: str | None
    resolution_name: str | None
    candidates_considered: list[str] | None
    rationale: str | None
    forcing_perspective: str | None
    forcing_rationale: str | None
    evaluation_notes: str | None
    approver_name: str | None
    approver_role: str | None
    decision_date: datetime.date | None
    status: EngagementDecisionStatus
    warnings: list[str] = Field(
        description="Non-blocking, recomputed on every read — e.g. a Linux-incompatible resolution on a Linux-targeted engagement."
    )
    created_at: datetime.datetime
    updated_at: datetime.datetime


# ---------- coverage (Part H) ----------


class BlockingSignal(BaseModel):
    signal: str
    reason_code: str
    expected_extractor: str | None


class ItemCoverageEntry(BaseModel):
    item_id: str
    name: str
    scope: ItemScope
    reason_code: str
    blocking_by_extractor: dict[str, list[str]] = Field(
        description="Blocking signals grouped by expected extractor. '(none declared)' collects signals no extractor declares yet."
    )


class ItemCoverage(BaseModel):
    ready_count: int
    not_ready_count: int
    not_ready: list[ItemCoverageEntry]


class UnreferencedSignal(BaseModel):
    name: str
    category: str
    expected_extractor: str


class SignalCoverage(BaseModel):
    ready_signal_count: int
    referenced_ready_count: int
    unreferenced: list[UnreferencedSignal] = Field(
        description="Ready signals no active item references: either the extractor does unneeded work, or an item is missing."
    )


class ExtractorBacklogEntry(BaseModel):
    expected_extractor: str | None = Field(description="Null when no extractor declares the signal yet.")
    extractor_status: ExtractorStatus | None
    signals: list[str] = Field(description="Blocking signals this extractor would supply.")
    items_blocked: list[str] = Field(description="Items this extractor's signals block.")
    items_unblocked: list[str] = Field(
        description="Items that become ready once this extractor lands, because it is their only remaining blocker."
    )


class ExtractorBacklog(BaseModel):
    entries: list[ExtractorBacklogEntry] = Field(description="Ordered by items_unblocked, then items_blocked.")
