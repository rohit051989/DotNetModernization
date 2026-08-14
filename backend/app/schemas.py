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
    """The rules a future scanning step will match a repository against to
    suggest this pattern. Purely declarative today — nothing evaluates these
    yet; see 10-ENGINE-CONCEPTS.md for the step that eventually will."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "target_frameworks": ["net48"],
                    "required_namespaces": ["System.ServiceModel"],
                    "forbidden_namespaces": [],
                    "required_packages": [],
                    "file_globs": ["**/*.svc"],
                    "forbidden_file_globs": [],
                    "project_properties": {"OutputType": "Library"},
                    "config_markers": ["<system.serviceModel>"],
                    "confidence_weight": 1.0,
                    "notes": "High confidence when a .svc file and a system.serviceModel config section co-occur.",
                }
            ]
        },
    )

    target_frameworks: list[str] = Field(
        default_factory=list,
        description="TFMs this pattern applies to, e.g. 'net48' or 'netcoreapp2.1'. Empty means framework-independent.",
    )
    required_namespaces: list[str] = Field(
        default_factory=list, description="Namespaces whose presence in source is a positive signal."
    )
    forbidden_namespaces: list[str] = Field(
        default_factory=list, description="Namespaces whose presence rules this pattern out."
    )
    required_packages: list[str] = Field(
        default_factory=list, description="NuGet package ids expected to be referenced."
    )
    file_globs: list[str] = Field(
        default_factory=list, description="Glob patterns whose presence is a positive signal, e.g. '**/*.svc'."
    )
    forbidden_file_globs: list[str] = Field(
        default_factory=list, description="Glob patterns whose presence rules this pattern out."
    )
    project_properties: dict[str, str] = Field(
        default_factory=dict, description="MSBuild properties (name -> expected value) that support the match."
    )
    config_markers: list[str] = Field(
        default_factory=list, description="Literal strings expected in config files, e.g. an XML element name."
    )
    confidence_weight: float = Field(
        default=1.0, description="Relative weight this rule set contributes to an overall match score."
    )
    notes: str | None = Field(default=None, description="Free-text notes on why these rules were chosen.")


class EngineSupport(BaseModel):
    """How well the GitHub Copilot app modernization engine covers this
    target state option today — informs how much custom skill work a
    migration will need."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "engine": "github-copilot-app-modernization",
                    "coverage": "strong",
                    "scenarios": ["dotnet-upgrade"],
                    "skills": [],
                    "gaps": [],
                    "custom_skills_required": [],
                }
            ]
        },
    )

    engine: str | None = Field(default=None, description="Identifier of the transformation engine assessed.")
    coverage: EngineCoverage | None = Field(
        default=None, description="Overall coverage: 'none', 'partial', or 'strong'."
    )
    scenarios: list[str] = Field(
        default_factory=list, description="Named engine scenarios/playbooks that apply."
    )
    skills: list[str] = Field(default_factory=list, description="Built-in engine skills invoked.")
    gaps: list[str] = Field(
        default_factory=list, description="Known things the engine does not handle for this target state."
    )
    custom_skills_required: list[str] = Field(
        default_factory=list,
        description="Our own skills/sub-agents needed to close the gaps above.",
    )


# ---------- Patterns ----------


class PatternBase(BaseModel):
    name: str = Field(description="Human-readable pattern name.", examples=[".NET Core 2.x REST API"])
    summary: str = Field(
        description="One-sentence description shown in list views.",
        examples=["ASP.NET Core 2.x Web API with Startup-based hosting, running on IIS."],
    )
    description: str | None = Field(
        default=None, description="Longer explanation, markdown supported. Shown on the pattern detail page."
    )
    legacy_stack: str = Field(
        description="The legacy technology stack this pattern identifies.", examples=[".NET Core 2.0 - 2.2"]
    )
    category: str = Field(
        description="Free-text grouping used for filtering, e.g. 'web-api', 'wcf', 'batch'.",
        examples=["web-api"],
    )
    detection_rules: DetectionRules = Field(description="Structured rules a future scan step matches against.")
    typical_indicators: str | None = Field(
        default=None, description="Human-readable cues an engineer would notice, distinct from `detection_rules`."
    )
    known_risks: str | None = Field(
        default=None, description="Risks or gotchas worth knowing before migrating this pattern."
    )


class PatternCreate(PatternBase):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "core2-rest-api",
                    "name": ".NET Core 2.x REST API",
                    "summary": "ASP.NET Core 2.x Web API with Startup-based hosting, running on IIS.",
                    "description": "REST API built on ASP.NET Core 2.0-2.2 using the classic Startup.cs ConfigureServices/Configure pair.",
                    "legacy_stack": ".NET Core 2.0 - 2.2",
                    "category": "web-api",
                    "detection_rules": {
                        "target_frameworks": ["netcoreapp2.0", "netcoreapp2.1", "netcoreapp2.2"],
                        "required_namespaces": ["Microsoft.AspNetCore.Mvc"],
                        "required_packages": [],
                        "file_globs": ["**/Startup.cs"],
                        "forbidden_file_globs": [],
                        "config_markers": [],
                        "confidence_weight": 1.0,
                    },
                    "typical_indicators": "Startup.cs with ConfigureServices/Configure, Program.cs with WebHost.CreateDefaultBuilder.",
                    "known_risks": "Default JSON serializer changes from Newtonsoft to System.Text.Json on modern .NET.",
                    "status": "active",
                }
            ]
        }
    )

    id: str = Field(
        description="Slug, lowercase and hyphenated. Immutable once created.", examples=["core2-rest-api"]
    )
    status: LifecycleStatus = Field(
        default="active", description="Lifecycle state: 'draft', 'active', or 'deprecated'."
    )

    @field_validator("id")
    @classmethod
    def _check_id_slug(cls, v: str) -> str:
        return _validate_slug(v)


class PatternUpdate(PatternBase):
    status: LifecycleStatus | None = Field(
        default=None, description="Lifecycle state. Omit to leave unchanged."
    )


class TargetStateSummary(BaseModel):
    """The shape a target state option takes when nested under a pattern
    response, rather than fetched on its own (see `TargetStateDetail`)."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Slug identifying this option.")
    pattern_id: str = Field(description="The pattern this option belongs to.")
    name: str = Field(description="Human-readable option name.")
    summary: str = Field(description="One-sentence description.")
    target_stack: str = Field(description="The technology stack this option migrates to.")
    consumer_impact: ConsumerImpact = Field(
        description="How much this option changes what existing callers see: 'none', 'low', 'medium', or 'high'."
    )
    effort: EffortLevel = Field(description="Relative migration effort: 'low', 'medium', or 'high'.")
    linux_compatible: bool = Field(description="Whether the resulting stack runs on Linux.")
    container_ready: bool = Field(description="Whether the resulting stack is container-friendly as-is.")
    is_lift_and_shift: bool = Field(description="Whether this is the lowest-effort, lowest-risk default option.")
    is_recommended: bool = Field(
        description="Whether this is the master catalog's own recommended option for the pattern. At most one per pattern."
    )
    status: LifecycleStatus = Field(description="Lifecycle state: 'draft', 'active', or 'deprecated'.")
    version: int = Field(description="Increments on any material change (name, target_stack, consumer_impact, effort).")
    updated_at: datetime.datetime = Field(description="When this option was last modified.")


class PatternSummary(BaseModel):
    """The list-view shape for a pattern — no `detection_rules` or nested
    target states, to keep `GET /api/patterns` cheap."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Slug identifying this pattern.")
    name: str = Field(description="Human-readable pattern name.")
    summary: str = Field(description="One-sentence description.")
    legacy_stack: str = Field(description="The legacy technology stack this pattern identifies.")
    category: str = Field(description="Free-text grouping used for filtering.")
    status: LifecycleStatus = Field(description="Lifecycle state: 'draft', 'active', or 'deprecated'.")
    version: int = Field(description="Increments on any material change (detection_rules, name, legacy_stack, category).")
    target_state_count: int = Field(
        description="Number of non-deleted, non-deprecated target state options under this pattern."
    )
    updated_at: datetime.datetime = Field(description="When this pattern was last modified.")
    deleted_at: datetime.datetime | None = Field(
        description="When this pattern was soft-deleted, or null if it is live."
    )
    deleted_by: str | None = Field(description="Free-text identity that soft-deleted this pattern, if any.")


class PatternDetail(BaseModel):
    """The full pattern shape, including detection rules and every
    non-deleted target state option."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Slug identifying this pattern.")
    name: str = Field(description="Human-readable pattern name.")
    summary: str = Field(description="One-sentence description.")
    description: str | None = Field(description="Longer explanation, markdown supported.")
    legacy_stack: str = Field(description="The legacy technology stack this pattern identifies.")
    category: str = Field(description="Free-text grouping used for filtering.")
    detection_rules: dict = Field(description="Structured rules a future scan step matches against.")
    typical_indicators: str | None = Field(description="Human-readable cues an engineer would notice.")
    known_risks: str | None = Field(description="Risks or gotchas worth knowing before migrating this pattern.")
    status: LifecycleStatus = Field(description="Lifecycle state: 'draft', 'active', or 'deprecated'.")
    version: int = Field(description="Increments on any material change (detection_rules, name, legacy_stack, category).")
    created_at: datetime.datetime = Field(description="When this pattern was created.")
    updated_at: datetime.datetime = Field(description="When this pattern was last modified.")
    deleted_at: datetime.datetime | None = Field(description="When this pattern was soft-deleted, or null if live.")
    deleted_by: str | None = Field(description="Free-text identity that soft-deleted this pattern, if any.")
    target_state_options: list[TargetStateSummary] = Field(
        description="Non-deleted target state options for this pattern, lowest consumer_impact first."
    )


class PatternDeprecateResponse(BaseModel):
    id: str = Field(description="The pattern's id.")
    status: LifecycleStatus = Field(description="Always 'deprecated' after this call succeeds.")
    referenced_by_decisions: int = Field(
        description="Count of non-superseded, non-deleted decision records (across every engagement) still referencing this pattern. Informational — deprecation is permissive and always succeeds."
    )


class PatternSoftDeleteResponse(BaseModel):
    id: str = Field(description="The pattern's id.")
    deleted_at: datetime.datetime | None = Field(description="When the soft delete took effect.")


# ---------- Target state options ----------


class TargetStateBase(BaseModel):
    name: str = Field(description="Human-readable option name, unique within its pattern.")
    summary: str = Field(description="One-sentence description.")
    target_stack: str = Field(description="The technology stack this option migrates to.")
    consumer_impact: ConsumerImpact = Field(
        description="How much this option changes what existing callers see: 'none', 'low', 'medium', or 'high'."
    )
    effort: EffortLevel = Field(description="Relative migration effort: 'low', 'medium', or 'high'.")
    linux_compatible: bool = Field(default=True, description="Whether the resulting stack runs on Linux.")
    container_ready: bool = Field(default=True, description="Whether the resulting stack is container-friendly as-is.")
    is_lift_and_shift: bool = Field(
        default=False, description="Whether this is the lowest-effort, lowest-risk default option."
    )
    is_recommended: bool = Field(
        default=False,
        description="Master-catalog recommendation flag. Setting true on one option clears it on every other option under the same pattern.",
    )
    engine_support: EngineSupport | None = Field(
        default=None, description="Assessed coverage from the Copilot app modernization engine."
    )
    playbook_md: str | None = Field(default=None, description="Markdown playbook for executing this migration.")
    prerequisites: str | None = Field(default=None, description="What must be true before starting this migration.")
    known_limitations: str | None = Field(default=None, description="Known limitations of this option.")


class TargetStateCreate(TargetStateBase):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "net10-api-controllers-preserved",
                    "name": ".NET 10 Web API, controllers preserved",
                    "summary": "Retarget to .NET 10, keep controller classes and routes exactly as they are.",
                    "target_stack": ".NET 10 + ASP.NET Core, container on OCP4",
                    "consumer_impact": "none",
                    "effort": "low",
                    "linux_compatible": True,
                    "container_ready": True,
                    "is_lift_and_shift": True,
                    "is_recommended": True,
                    "status": "active",
                }
            ]
        }
    )

    id: str = Field(description="Slug, lowercase and hyphenated. Immutable once created.")
    status: LifecycleStatus = Field(
        default="active", description="Lifecycle state: 'draft', 'active', or 'deprecated'."
    )

    @field_validator("id")
    @classmethod
    def _check_id_slug(cls, v: str) -> str:
        return _validate_slug(v)


class TargetStateUpdate(TargetStateBase):
    status: LifecycleStatus | None = Field(default=None, description="Lifecycle state. Omit to leave unchanged.")


class TargetStateDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Slug identifying this option.")
    pattern_id: str = Field(description="The pattern this option belongs to.")
    name: str = Field(description="Human-readable option name.")
    summary: str = Field(description="One-sentence description.")
    target_stack: str = Field(description="The technology stack this option migrates to.")
    consumer_impact: ConsumerImpact = Field(description="'none', 'low', 'medium', or 'high'.")
    effort: EffortLevel = Field(description="'low', 'medium', or 'high'.")
    linux_compatible: bool = Field(description="Whether the resulting stack runs on Linux.")
    container_ready: bool = Field(description="Whether the resulting stack is container-friendly as-is.")
    is_lift_and_shift: bool = Field(description="Whether this is the lowest-effort, lowest-risk default option.")
    is_recommended: bool = Field(description="Master-catalog recommendation flag. At most one true per pattern.")
    engine_support: dict | None = Field(description="Assessed coverage from the Copilot app modernization engine.")
    playbook_md: str | None = Field(description="Markdown playbook for executing this migration.")
    prerequisites: str | None = Field(description="What must be true before starting this migration.")
    known_limitations: str | None = Field(description="Known limitations of this option.")
    status: LifecycleStatus = Field(description="Lifecycle state: 'draft', 'active', or 'deprecated'.")
    version: int = Field(description="Increments on any material change.")
    created_at: datetime.datetime = Field(description="When this option was created.")
    updated_at: datetime.datetime = Field(description="When this option was last modified.")
    deleted_at: datetime.datetime | None = Field(description="When this option was soft-deleted, or null if live.")
    deleted_by: str | None = Field(description="Free-text identity that soft-deleted this option, if any.")


class TargetStateDeprecateResponse(BaseModel):
    id: str = Field(description="The target state option's id.")
    status: LifecycleStatus = Field(description="Always 'deprecated' after this call succeeds.")


class TargetStateSoftDeleteResponse(BaseModel):
    id: str = Field(description="The target state option's id.")
    deleted_at: datetime.datetime | None = Field(description="When the soft delete took effect.")


# ---------- Engagements ----------


class EngagementBase(BaseModel):
    client_name: str = Field(description="Display name of the client this engagement is for.")
    description: str | None = Field(default=None, description="Free-text notes about this engagement.")
    target_platform: str | None = Field(
        default=None, description="Intended deployment target, e.g. 'OpenShift 4'."
    )
    default_posture: str = Field(
        default="lift-and-shift",
        description="Default migration posture for this engagement, e.g. 'lift-and-shift'.",
    )


class EngagementCreate(EngagementBase):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "client-a-ocp4",
                    "client_name": "Client A",
                    "description": "Estate migration to OpenShift 4.",
                    "target_platform": "OpenShift 4",
                    "default_posture": "lift-and-shift",
                }
            ]
        }
    )

    id: str = Field(description="Slug identifying this engagement. Immutable once created.")


class EngagementUpdate(EngagementBase):
    status: LifecycleStatus | None = Field(default=None, description="Lifecycle state. Omit to leave unchanged.")


class Engagement(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Slug identifying this engagement.")
    client_name: str = Field(description="Display name of the client this engagement is for.")
    description: str | None = Field(description="Free-text notes about this engagement.")
    target_platform: str | None = Field(description="Intended deployment target, e.g. 'OpenShift 4'.")
    default_posture: str = Field(description="Default migration posture for this engagement.")
    status: LifecycleStatus = Field(description="Lifecycle state: 'draft', 'active', or 'deprecated'.")
    created_at: datetime.datetime = Field(description="When this engagement was created.")
    updated_at: datetime.datetime = Field(description="When this engagement was last modified.")
    deleted_at: datetime.datetime | None = Field(description="When this engagement was soft-deleted, or null if live.")
    deleted_by: str | None = Field(description="Free-text identity that soft-deleted this engagement, if any.")


class CoverageSummary(BaseModel):
    """Decision-record coverage for one engagement — feeds the future
    dashboard. See 03-BACKEND-SPEC.md for exactly what each count includes."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "engagement_id": "client-a-ocp4",
                    "total_patterns": 8,
                    "approved": 5,
                    "in_review": 1,
                    "parked": 2,
                    "deferred": 1,
                    "patterns_without_decision": ["ssis-package"],
                }
            ]
        }
    )

    engagement_id: str = Field(description="The engagement this summary is for.")
    total_patterns: int = Field(
        description="Non-deleted, active master patterns, minus any this engagement has client-deleted."
    )
    approved: int = Field(description="This engagement's non-superseded, non-deleted decisions with status 'approved'.")
    in_review: int = Field(description="This engagement's non-superseded, non-deleted decisions with status 'in_review'.")
    parked: int = Field(description="This engagement's non-superseded, non-deleted decisions with status 'parked'.")
    deferred: int = Field(description="Patterns this engagement has deferred, regardless of decision status.")
    patterns_without_decision: list[str] = Field(
        description="Master pattern ids with neither a decision record nor a defer/delete overlay in this engagement."
    )


# ---------- Decision records ----------


class DecisionRecordUpsert(BaseModel):
    """Body for `PUT /api/engagements/{eid}/patterns/{pid}/decision` — the
    identity (engagement, pattern) is fully in the path, so it is not
    repeated here. Creates the live decision if none exists yet, otherwise
    updates it in place; omitted fields leave an existing value unchanged."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "selected_target_state_id": "net10-api-controllers-preserved",
                    "candidates_considered": ["net10-api-controllers-preserved", "grpc-rewrite"],
                    "evaluation_notes": "gRPC rewrite was considered but adds unnecessary consumer impact.",
                    "forcing_factor": None,
                    "rationale": "Lowest-impact option; no forcing factor applies.",
                    "approver_name": "J. Rivera",
                    "approver_role": "Engagement Lead",
                    "decision_date": "2026-08-01",
                    "status": "approved",
                }
            ]
        }
    )

    selected_target_state_id: str | None = Field(
        default=None, description="Chosen target state option id. Must belong to this pattern."
    )
    candidates_considered: list[str] | None = Field(
        default=None, description="Target state option ids weighed before choosing."
    )
    evaluation_notes: str | None = Field(default=None, description="Free-text notes on the evaluation.")
    forcing_factor: str | None = Field(
        default=None,
        description="Required when the selection is not the lowest consumer_impact among candidates_considered — the security requirement or decommissioned dependency that justifies the deviation.",
    )
    rationale: str | None = Field(default=None, description="Required when status is 'approved'.")
    approver_name: str | None = Field(default=None, description="Required when status is 'approved'.")
    approver_role: str | None = Field(default=None, description="Approver's role or title.")
    decision_date: datetime.date | None = Field(default=None, description="Required when status is 'approved'.")
    status: DecisionStatus = Field(
        default="parked", description="'parked', 'in_review', 'approved', or 'superseded'."
    )


class DecisionRecordUpdate(BaseModel):
    """Body for `PUT /api/decisions/{decision_id}` — editing a specific
    record by its own id, including historical (superseded) ones. Omitted
    fields leave the existing value unchanged."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "selected_target_state_id": "net10-api-controllers-preserved",
                    "candidates_considered": ["net10-api-controllers-preserved"],
                    "evaluation_notes": None,
                    "forcing_factor": None,
                    "rationale": "Lowest-impact option; no forcing factor applies.",
                    "approver_name": "J. Rivera",
                    "approver_role": "Engagement Lead",
                    "decision_date": "2026-08-01",
                    "status": "approved",
                }
            ]
        }
    )

    selected_target_state_id: str | None = Field(
        default=None, description="Chosen target state option id. Must belong to this decision's pattern."
    )
    candidates_considered: list[str] | None = Field(
        default=None, description="Target state option ids weighed before choosing."
    )
    evaluation_notes: str | None = Field(default=None, description="Free-text notes on the evaluation.")
    forcing_factor: str | None = Field(
        default=None,
        description="Required when the selection is not the lowest consumer_impact among candidates_considered.",
    )
    rationale: str | None = Field(default=None, description="Required when status is 'approved'.")
    approver_name: str | None = Field(default=None, description="Required when status is 'approved'.")
    approver_role: str | None = Field(default=None, description="Approver's role or title.")
    decision_date: datetime.date | None = Field(default=None, description="Required when status is 'approved'.")
    status: DecisionStatus | None = Field(
        default=None, description="'parked', 'in_review', 'approved', or 'superseded'. Omit to leave unchanged."
    )


class DecisionRecord(BaseModel):
    """An engagement's choice (or in-progress evaluation) of target state for
    one pattern. `pattern_name` and `selected_target_state_name` are joined
    in so the UI needs no extra lookups."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="This decision record's id.")
    engagement_id: str = Field(description="The engagement this decision belongs to.")
    pattern_id: str = Field(description="The pattern this decision is for.")
    pattern_name: str = Field(description="Denormalised for display.")
    selected_target_state_id: str | None = Field(description="Chosen target state option id, if any yet.")
    selected_target_state_name: str | None = Field(description="Denormalised for display.")
    candidates_considered: list[str] | None = Field(description="Target state option ids weighed before choosing.")
    evaluation_notes: str | None = Field(description="Free-text notes on the evaluation.")
    forcing_factor: str | None = Field(
        description="The security requirement or decommissioned dependency that justified a higher-impact choice, if any."
    )
    rationale: str | None = Field(description="Why this choice was made.")
    approver_name: str | None = Field(description="Who approved this decision.")
    approver_role: str | None = Field(description="The approver's role or title.")
    decision_date: datetime.date | None = Field(description="When this decision was approved.")
    status: DecisionStatus = Field(description="'parked', 'in_review', 'approved', or 'superseded'.")
    created_at: datetime.datetime = Field(description="When this record was created.")
    updated_at: datetime.datetime = Field(description="When this record was last modified.")
    deleted_at: datetime.datetime | None = Field(description="When this record was soft-deleted, or null if live.")
    deleted_by: str | None = Field(description="Free-text identity that soft-deleted this record, if any.")


# ---------- Client-scoped patterns (engagement_patterns overlay) ----------


class EngagementPatternDeferRequest(BaseModel):
    deferred_reason: str | None = Field(
        default=None, description="Free-text reason this engagement is deferring the pattern."
    )


class EngagementPatternView(BaseModel):
    """A merged read model, not a stored row: master pattern fields (full
    PatternDetail shape) joined with this engagement's overlay state and a
    lightweight decision summary. See 02-DATA-MODEL.md's lazy-overlay note —
    scope_status/deleted_at here reflect 'active'/None when no overlay row
    exists, exactly as if a row existed saying so explicitly."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "engagement_id": "client-a-ocp4",
                    "pattern_id": "core2-rest-api",
                    "name": ".NET Core 2.x REST API",
                    "summary": "ASP.NET Core 2.x Web API with Startup-based hosting, running on IIS.",
                    "description": None,
                    "legacy_stack": ".NET Core 2.0 - 2.2",
                    "category": "web-api",
                    "detection_rules": {},
                    "typical_indicators": None,
                    "known_risks": None,
                    "status": "active",
                    "version": 1,
                    "target_state_options": [],
                    "scope_status": "active",
                    "deferred_reason": None,
                    "deleted_at": None,
                    "deleted_by": None,
                    "decision_status": "approved",
                    "selected_target_state_name": ".NET 10 Web API, controllers preserved",
                }
            ]
        }
    )

    engagement_id: str = Field(description="The engagement this view is scoped to.")
    pattern_id: str = Field(description="The master pattern this view merges.")
    name: str = Field(description="Master pattern name.")
    summary: str = Field(description="Master pattern summary.")
    description: str | None = Field(description="Master pattern description.")
    legacy_stack: str = Field(description="Master pattern legacy stack.")
    category: str = Field(description="Master pattern category.")
    detection_rules: dict = Field(description="Master pattern detection rules.")
    typical_indicators: str | None = Field(description="Master pattern typical indicators.")
    known_risks: str | None = Field(description="Master pattern known risks.")
    status: LifecycleStatus = Field(description="Master pattern lifecycle state.")
    version: int = Field(description="Master pattern version.")
    created_at: datetime.datetime = Field(description="Master pattern creation time.")
    updated_at: datetime.datetime = Field(description="Master pattern last-modified time.")
    target_state_options: list[TargetStateSummary] = Field(description="Master target state options for this pattern.")
    scope_status: ScopeStatus = Field(
        description="This engagement's overlay: 'active' or 'deferred'. Reads 'active' when no overlay row exists."
    )
    deferred_reason: str | None = Field(description="Why this engagement deferred the pattern, if deferred.")
    deleted_at: datetime.datetime | None = Field(
        description="When this engagement client-deleted the pattern, or null if not deleted here. Independent of the master pattern's own deleted_at."
    )
    deleted_by: str | None = Field(description="Free-text identity that client-deleted the pattern here, if any.")
    decision_status: DecisionStatus | None = Field(
        description="This engagement's live decision status for the pattern, or null if none recorded yet."
    )
    selected_target_state_name: str | None = Field(
        description="Denormalised name of the live decision's selected target state, if any."
    )


class EngagementPatternSoftDeleteResponse(BaseModel):
    engagement_id: str = Field(description="The engagement this soft delete is scoped to.")
    pattern_id: str = Field(description="The pattern that was client-scoped soft-deleted.")
    deleted_at: datetime.datetime | None = Field(description="When the soft delete took effect, or null if restored.")


# ---------- Catalog export / import ----------


class CatalogExport(BaseModel):
    """Deterministic, diffable catalog snapshot — see 03-BACKEND-SPEC.md's
    'The export must be deterministic' section. Also the request body shape
    for import."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "catalog_version": "1.0",
                    "exported_at": "2026-08-05T00:00:00Z",
                    "patterns": [
                        {
                            "id": "core2-rest-api",
                            "name": ".NET Core 2.x REST API",
                            "target_state_options": [],
                        }
                    ],
                    "engagements": [],
                    "decision_records": [],
                }
            ]
        }
    )

    catalog_version: str = Field(description="Schema version of this export format.")
    exported_at: str = Field(description="ISO-8601 UTC timestamp this export was generated.")
    patterns: list[dict] = Field(
        default_factory=list, description="Pattern records, each with nested target_state_options."
    )
    engagements: list[dict] = Field(
        default_factory=list, description="Engagement records. Populated only for scope=engagement exports."
    )
    decision_records: list[dict] = Field(
        default_factory=list, description="Decision records. Populated only for scope=engagement exports."
    )


class CatalogImportResult(BaseModel):
    patterns_created: int = Field(description="New patterns inserted by this import.")
    patterns_updated: int = Field(description="Existing patterns overwritten by this import.")
    target_state_options_created: int = Field(description="New target state options inserted.")
    target_state_options_updated: int = Field(description="Existing target state options overwritten.")
    engagements_created: int = Field(description="New engagements inserted.")
    engagements_updated: int = Field(description="Existing engagements overwritten.")
    decision_records_created: int = Field(description="New decision records inserted.")
    decision_records_updated: int = Field(description="Existing decision records overwritten.")
