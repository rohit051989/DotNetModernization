import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LifecycleStatus = Literal["draft", "active", "deprecated"]
ConsumerImpact = Literal["none", "low", "medium", "high"]
EffortLevel = Literal["low", "medium", "high"]
DecisionStatus = Literal["parked", "in_review", "approved", "superseded"]
EngineCoverage = Literal["none", "partial", "strong"]
ScopeStatus = Literal["active", "deferred"]

CONSUMER_IMPACT_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}
EFFORT_RANK = {"low": 0, "medium": 1, "high": 2}

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _validate_slug(value: str) -> str:
    if not SLUG_PATTERN.match(value):
        raise ValueError(
            f"'{value}' is not a valid slug; expected lowercase, hyphenated "
            "(e.g. 'wcf-iis-servicemodel')"
        )
    return value


class DetectionRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_frameworks: list[str] = Field(default_factory=list)
    required_namespaces: list[str] = Field(default_factory=list)
    forbidden_namespaces: list[str] = Field(default_factory=list)
    required_packages: list[str] = Field(default_factory=list)
    file_globs: list[str] = Field(default_factory=list)
    forbidden_file_globs: list[str] = Field(default_factory=list)
    project_properties: dict[str, str] = Field(default_factory=dict)
    config_markers: list[str] = Field(default_factory=list)
    confidence_weight: float = 1.0
    notes: str | None = None


class EngineSupport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: str | None = None
    coverage: EngineCoverage | None = None
    scenarios: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    custom_skills_required: list[str] = Field(default_factory=list)


# ---------- Patterns ----------


class PatternBase(BaseModel):
    name: str
    summary: str
    description: str | None = None
    legacy_stack: str
    category: str
    detection_rules: DetectionRules
    typical_indicators: str | None = None
    known_risks: str | None = None


class PatternCreate(PatternBase):
    id: str
    status: LifecycleStatus = "active"

    @field_validator("id")
    @classmethod
    def _check_id_slug(cls, v: str) -> str:
        return _validate_slug(v)


class PatternUpdate(PatternBase):
    status: LifecycleStatus | None = None


class TargetStateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pattern_id: str
    name: str
    summary: str
    target_stack: str
    consumer_impact: ConsumerImpact
    effort: EffortLevel
    linux_compatible: bool
    container_ready: bool
    is_lift_and_shift: bool
    is_recommended: bool
    status: LifecycleStatus
    version: int
    updated_at: datetime.datetime


class PatternSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    summary: str
    legacy_stack: str
    category: str
    status: LifecycleStatus
    version: int
    target_state_count: int
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    deleted_by: str | None


class PatternDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    summary: str
    description: str | None
    legacy_stack: str
    category: str
    detection_rules: dict
    typical_indicators: str | None
    known_risks: str | None
    status: LifecycleStatus
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    deleted_by: str | None
    target_state_options: list[TargetStateSummary]


class PatternDeprecateResponse(BaseModel):
    id: str
    status: LifecycleStatus
    referenced_by_decisions: int


class PatternSoftDeleteResponse(BaseModel):
    id: str
    deleted_at: datetime.datetime | None


# ---------- Target state options ----------


class TargetStateBase(BaseModel):
    name: str
    summary: str
    target_stack: str
    consumer_impact: ConsumerImpact
    effort: EffortLevel
    linux_compatible: bool = True
    container_ready: bool = True
    is_lift_and_shift: bool = False
    is_recommended: bool = False
    engine_support: EngineSupport | None = None
    playbook_md: str | None = None
    prerequisites: str | None = None
    known_limitations: str | None = None


class TargetStateCreate(TargetStateBase):
    id: str
    status: LifecycleStatus = "active"

    @field_validator("id")
    @classmethod
    def _check_id_slug(cls, v: str) -> str:
        return _validate_slug(v)


class TargetStateUpdate(TargetStateBase):
    status: LifecycleStatus | None = None


class TargetStateDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pattern_id: str
    name: str
    summary: str
    target_stack: str
    consumer_impact: ConsumerImpact
    effort: EffortLevel
    linux_compatible: bool
    container_ready: bool
    is_lift_and_shift: bool
    is_recommended: bool
    engine_support: dict | None
    playbook_md: str | None
    prerequisites: str | None
    known_limitations: str | None
    status: LifecycleStatus
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    deleted_by: str | None


class TargetStateDeprecateResponse(BaseModel):
    id: str
    status: LifecycleStatus


class TargetStateSoftDeleteResponse(BaseModel):
    id: str
    deleted_at: datetime.datetime | None


# ---------- Engagements ----------


class EngagementBase(BaseModel):
    client_name: str
    description: str | None = None
    target_platform: str | None = None
    default_posture: str = "lift-and-shift"


class EngagementCreate(EngagementBase):
    id: str


class EngagementUpdate(EngagementBase):
    status: LifecycleStatus | None = None


class Engagement(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_name: str
    description: str | None
    target_platform: str | None
    default_posture: str
    status: LifecycleStatus
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    deleted_by: str | None


class CoverageSummary(BaseModel):
    engagement_id: str
    total_patterns: int
    approved: int
    in_review: int
    parked: int
    deferred: int
    patterns_without_decision: list[str]


# ---------- Decision records ----------


class DecisionRecordCreate(BaseModel):
    pattern_id: str
    selected_target_state_id: str | None = None
    candidates_considered: list[str] | None = None
    evaluation_notes: str | None = None
    forcing_factor: str | None = None
    rationale: str | None = None
    approver_name: str | None = None
    approver_role: str | None = None
    decision_date: datetime.date | None = None
    status: DecisionStatus = "parked"


class DecisionRecordUpdate(BaseModel):
    selected_target_state_id: str | None = None
    candidates_considered: list[str] | None = None
    evaluation_notes: str | None = None
    forcing_factor: str | None = None
    rationale: str | None = None
    approver_name: str | None = None
    approver_role: str | None = None
    decision_date: datetime.date | None = None
    status: DecisionStatus | None = None


class DecisionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    engagement_id: str
    pattern_id: str
    pattern_name: str
    selected_target_state_id: str | None
    selected_target_state_name: str | None
    candidates_considered: list[str] | None
    evaluation_notes: str | None
    forcing_factor: str | None
    rationale: str | None
    approver_name: str | None
    approver_role: str | None
    decision_date: datetime.date | None
    status: DecisionStatus
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    deleted_by: str | None


# ---------- Client-scoped patterns (engagement_patterns overlay) ----------


class EngagementPatternDeferRequest(BaseModel):
    deferred_reason: str | None = None


class EngagementPatternView(BaseModel):
    """A merged read model, not a stored row: master pattern fields (full
    PatternDetail shape) joined with this engagement's overlay state and a
    lightweight decision summary. See 02-DATA-MODEL.md's lazy-overlay note —
    scope_status/deleted_at here reflect 'active'/None when no overlay row
    exists, exactly as if a row existed saying so explicitly."""

    engagement_id: str
    pattern_id: str
    name: str
    summary: str
    description: str | None
    legacy_stack: str
    category: str
    detection_rules: dict
    typical_indicators: str | None
    known_risks: str | None
    status: LifecycleStatus
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    target_state_options: list[TargetStateSummary]
    scope_status: ScopeStatus
    deferred_reason: str | None
    deleted_at: datetime.datetime | None
    deleted_by: str | None
    decision_status: DecisionStatus | None
    selected_target_state_name: str | None


class EngagementPatternSoftDeleteResponse(BaseModel):
    engagement_id: str
    pattern_id: str
    deleted_at: datetime.datetime | None


# ---------- Catalog export / import ----------


class CatalogExport(BaseModel):
    catalog_version: str
    exported_at: str
    patterns: list[dict] = Field(default_factory=list)
    engagements: list[dict] = Field(default_factory=list)
    decision_records: list[dict] = Field(default_factory=list)


class CatalogImportResult(BaseModel):
    patterns_created: int
    patterns_updated: int
    target_state_options_created: int
    target_state_options_updated: int
    engagements_created: int
    engagements_updated: int
    decision_records_created: int
    decision_records_updated: int
