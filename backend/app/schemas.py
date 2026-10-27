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
ClassificationRole = Literal["PRIMARY", "SECONDARY", "PROJECT_ROLE"]
PatternScope = Literal["PROJECT", "REPOSITORY"]
RulesStatus = Literal["active", "awaiting_signals", "draft"]
ForcingPerspective = Literal[
    "SECURITY",
    "EVOLUTION",
    "REGULATION",
    "PERFORMANCE_SCALABILITY",
    "AVAILABILITY_RESILIENCE",
    "LOCATION",
    "DEVELOPMENT_RESOURCE",
]

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


# ---------- pattern-classification schema (24-PATTERN-CLASSIFICATION.md Part C) ----------
# Stored in `patterns.detection_rules` (legacy pattern tables, kept until the
# reset). The engine that evaluated it was removed with pattern-classification; the grammar
# lives on in catalog item detection (app/items/detection.py, evaluation.py).


class ValueMatch(BaseModel):
    """One value-matching operator for a signal or metadata condition. At
    most one field is expected to be set."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    equals: str | None = Field(default=None, description="Exact match.")
    in_: list[str] | None = Field(default=None, alias="in", description="Membership match against a list of values.")
    startsWith: str | None = Field(default=None, description="Prefix match.")
    contains: str | None = Field(default=None, description="Substring match.")
    regex: str | None = Field(
        default=None,
        description="Anchored regular expression. Checked for catastrophic backtracking at save time.",
    )


class SignalCondition(BaseModel):
    """A reference to one registered application-fingerprinting signal, with optional narrowing
    conditions (Part C 'Signal condition fields')."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        description="Registered signal name, e.g. 'SVC_FILE'. Checked against the active registry — see Part B3."
    )
    category: str | None = Field(default=None, description="Narrows to signals of this category.")
    type: str | None = Field(default=None, description="Narrows to signals of this type.")
    sourceType: str | None = Field(default=None, description="Narrows to signals observed from this evidence source type.")
    value: ValueMatch | None = Field(default=None, description="Narrows by the signal's captured value.")
    minimumOccurrences: int | None = Field(default=None, ge=1, description="Minimum occurrence count required.")
    maximumOccurrences: int | None = Field(default=None, ge=0, description="Maximum occurrence count allowed.")
    minimumDistinctValues: int | None = Field(default=None, ge=1)
    minimumDistinctSourceFiles: int | None = Field(default=None, ge=1)
    minimumExtractionConfidence: float | None = Field(default=None, ge=0.0, le=1.0)


class RuleCondition(BaseModel):
    """One entry in an `all` / `any` / `atLeast.of` group."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(
        default=None,
        description="Stable id referenced in matched_rules/failed_rules. Auto-generated positionally "
        "(e.g. 'all[0]') with a warning when omitted; required in practice for 'active' patterns.",
    )
    signal: SignalCondition


class SupportingCondition(RuleCondition):
    weight: float = Field(
        description="Added to the score when this condition matches. Summed across all matched supporting "
        "conditions and capped at 50 (Part E)."
    )


class NoneCondition(RuleCondition):
    disqualify: bool = Field(
        default=False,
        description="When true and this condition matches, the pattern cannot match regardless of score.",
    )
    penalty: float | None = Field(
        default=None,
        description="Subtracted from the score when this condition matches. Distinct from disqualify — "
        "Part C 'Negative conditions'.",
    )


class AtLeastGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(
        default=None, description="Auto-generated positionally (e.g. 'atLeast[0]') when omitted."
    )
    count: int = Field(ge=1, description="Minimum number of `of` entries that must match.")
    of: list[RuleCondition] = Field(description="Candidate conditions; at least `count` of these must match.")


class MetadataCondition(BaseModel):
    """A condition against solution-discovery or application-fingerprinting project metadata rather than a signal
    (Part C 'Metadata conditions'), e.g. `{"field": "outputType", "equals": "Library"}`."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str | None = Field(
        default=None, description="Auto-generated positionally (e.g. 'metadata[0]') when omitted."
    )
    field: str = Field(description="Project metadata field, e.g. 'outputType', 'projectSdk', 'fingerprintStatus'.")
    equals: str | None = Field(default=None, description="Exact match.")
    in_: list[str] | None = Field(default=None, alias="in", description="Membership match.")
    startsWith: str | None = Field(default=None, description="Prefix match.")
    contains: str | None = Field(default=None, description="Substring match.")
    regex: str | None = Field(default=None, description="Anchored regular expression.")
    notEquals: str | None = Field(
        default=None,
        description="Exclusion: the condition fails when the field equals this. The `none` group only accepts "
        "signal conditions, so a metadata-based exclusion (e.g. 'outputType is not WinExe') has to be expressed "
        "here. An absent field value passes — it cannot equal the excluded value.",
    )
    notIn: list[str] | None = Field(
        default=None,
        description="Exclusion against a list. An absent field value passes, as with notEquals.",
    )


class SignalRuleSet(BaseModel):
    """The Part C detection rule schema stored in `patterns.detection_rules`.
    All groups are optional; an absent or empty group imposes no constraint."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "schema": "signal-rules/1.0",
                    "all": [{"id": "wcf-contract", "signal": {"name": "SERVICE_CONTRACT_ATTRIBUTE", "minimumOccurrences": 1}}],
                    "any": [{"id": "svc-host", "signal": {"name": "SVC_FILE", "minimumOccurrences": 1}}],
                    "atLeast": [],
                    "supporting": [{"id": "operation-contract", "signal": {"name": "OPERATION_CONTRACT_ATTRIBUTE"}, "weight": 15}],
                    "none": [{"id": "is-test", "signal": {"name": "FACT_ATTRIBUTE", "minimumOccurrences": 1}, "disqualify": True}],
                    "metadata": [],
                }
            ]
        },
    )

    schema_: Literal["signal-rules/1.0"] = Field(alias="schema", description="Rule schema version tag.")
    all: list[RuleCondition] = Field(default_factory=list, description="Every condition here must match.")
    any: list[RuleCondition] = Field(default_factory=list, description="At least one condition here must match.")
    atLeast: list[AtLeastGroup] = Field(
        default_factory=list, description="Each group requires at least `count` of its `of` conditions to match."
    )
    supporting: list[SupportingCondition] = Field(
        default_factory=list, description="Weighted evidence that lifts the score above the base 50 (Part E)."
    )
    none: list[NoneCondition] = Field(default_factory=list, description="Negative evidence — disqualifying or penalizing.")
    metadata: list[MetadataCondition] = Field(
        default_factory=list, description="Conditions against project metadata rather than signals."
    )
    matchWarnings: list[str] = Field(
        default_factory=list,
        description="Shown (as project-level warnings) whenever this pattern matches. For a pattern whose "
        "detection is confident but its evidence is thin — e.g. metadata-only, no application-fingerprinting signal evidence yet "
        "— so that gap is visible on the match rather than implied by its absence.",
    )

    @classmethod
    def empty(cls) -> "SignalRuleSet":
        """The stub every pre-existing pattern is migrated to in J1 — inert
        until J2 re-authors real rules onto it."""
        return cls(schema="signal-rules/1.0")


class PatternEligibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fingerprintStatuses: list[str] = Field(
        default_factory=list,
        description="Fingerprint statuses this pattern may be evaluated against, e.g. ['COMPLETE', 'PARTIAL']. Empty means no constraint.",
    )
    excludedProjectRoles: list[str] = Field(
        default_factory=list,
        description="Project roles (Part D) excluded from this pattern, e.g. ['TEST', 'DEPLOYMENT'].",
    )


class PatternAnalysisRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: dict[str, bool] = Field(
        default_factory=dict,
        description="Analysis capabilities without which the pattern cannot be evaluated at all — capability_factor is 0 when absent (Part E).",
    )
    preferred: dict[str, bool] = Field(
        default_factory=dict,
        description="Analysis capabilities whose absence lowers confidence (capability_factor 0.9) but does not block evaluation.",
    )


class PatternThresholds(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"minimumScore": 70, "highConfidenceScore": 90}]},
    )

    minimumScore: int = Field(ge=0, le=100, description="Minimum match_score (Part E) for this pattern to count as matched.")
    highConfidenceScore: int = Field(
        ge=0, le=100, description="match_score at or above which a match is considered high-confidence."
    )


class RequiredSignalPending(BaseModel):
    """One entry in `required_signals_pending` — a signal this pattern's
    rules need but that application-fingerprinting does not yet produce (Part B2)."""

    model_config = ConfigDict(extra="forbid")

    signal_name: str = Field(description="The not-yet-registered signal name this pattern is waiting on.")
    purpose: str = Field(description="Why this signal matters to the pattern's rules.")
    expected_extractor: str = Field(description="The application-fingerprinting extractor expected to eventually produce this signal.")
    blocking: bool = Field(
        default=True,
        description="True if the pattern cannot be evaluated at all without this signal; false if it is enrichment only.",
    )


class SignalRegistryEntry(BaseModel):
    """One registered application-fingerprinting signal — Part B4: 'Every signal select shows
    its registry description.'"""

    name: str
    category: str
    type: str
    description: str
    extractor: str
    value_semantics: str
    weak_anchor: bool = Field(
        description="True for signals §7 says must not be a pattern's only anchor (e.g. PROGRAM_CS_FILE)."
    )


class SignalRegistryOut(BaseModel):
    registry_version: str
    signals: list[SignalRegistryEntry]


class PendingSignalPromotion(BaseModel):
    """One `awaiting_signals` pattern's promotion status against the
    currently active signal registry (Part B3)."""

    pattern_id: str = Field(description="The pattern's id.")
    name: str = Field(description="The pattern's display name.")
    required_signals_pending: list[dict] = Field(description="This pattern's full required_signals_pending list.")
    still_missing_blocking: list[str] = Field(
        description="Blocking pending signal names not yet in the active registry. Empty means the pattern is promotable."
    )
    promotable: bool = Field(
        description="True when every blocking pending signal is now registered. Promotion to 'active' remains a human action."
    )


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
    typical_indicators: str | None = Field(
        default=None, description="Human-readable cues an engineer would notice, distinct from the detection rules."
    )
    known_risks: str | None = Field(
        default=None, description="Risks or gotchas worth knowing before migrating this pattern."
    )

    # ---- pattern-classification schema (24-PATTERN-CLASSIFICATION.md Part B1) ----
    # Every field below is optional here: on create, omitting one applies the
    # same default the J1 migration gave existing patterns; on update,
    # omitting one leaves the current value untouched. None is never a valid
    # value to persist for these — it is purely the "not supplied" sentinel.
    detection_rules: SignalRuleSet | None = Field(
        default=None,
        description="Part C signal-rules/1.0 structure. Omit on create for an inert empty rule set; "
        "omit on update to leave the current rules untouched.",
    )
    classification_role: ClassificationRole | None = Field(
        default=None, description="'PRIMARY' (competes for the project's primary pattern), 'SECONDARY' "
        "(a coexisting capability), or 'PROJECT_ROLE' (Part D role determination). Defaults to 'PRIMARY'."
    )
    classification_family: str | None = Field(
        default=None, description="e.g. 'APPLICATION_TYPE', 'WEB_APPLICATION', 'CAPABILITY', 'PROJECT_ROLE'."
    )
    classification_value: str | None = Field(default=None, description="e.g. 'REST_API', 'WCF_SERVICE', 'TEST'.")
    scope: PatternScope | None = Field(
        default=None,
        description="'PROJECT' or 'REPOSITORY'. v1 evaluates PROJECT scope only (Part A8). Defaults to 'PROJECT'.",
    )
    priority: int | None = Field(default=None, description="Conflict tiebreak — higher wins. Defaults to 50.")
    compatible_with: list[str] | None = Field(
        default=None, description="Pattern ids this pattern may coexist with as a primary match. Defaults to []."
    )
    conflicts_with: list[str] | None = Field(
        default=None,
        description="Pattern ids this pattern cannot coexist with as a primary match. Rejected if any id also "
        "appears in `compatible_with`. Defaults to [].",
    )
    anchor_signals: list[str] | None = Field(
        default=None, description="Signal names used for the inverted candidate index. Defaults to []."
    )
    eligibility: PatternEligibility | None = Field(
        default=None, description="Fingerprint statuses and excluded project roles this pattern may be evaluated under."
    )
    analysis_requirements: PatternAnalysisRequirements | None = Field(
        default=None, description="Required vs preferred application-fingerprinting analysis capabilities."
    )
    thresholds: PatternThresholds | None = Field(
        default=None,
        description="{minimumScore, highConfidenceScore}. Defaults to {70, 90} on create, matching the "
        "worked example in the classification spec.",
    )
    rules_status: RulesStatus | None = Field(
        default=None,
        description="'active' (evaluated, signals must be registered), 'awaiting_signals' (evaluated once its "
        "pending signals land, may reference them early), or 'draft' (never evaluated). Defaults to 'draft'.",
    )
    required_signals_pending: list[RequiredSignalPending] | None = Field(
        default=None,
        description="Structured list of not-yet-registered signals this pattern's rules need. Required when "
        "`rules_status` is 'awaiting_signals' and the rules reference an unregistered signal. Defaults to [].",
    )


class PatternCreate(PatternBase):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "aspnetcore-rest-api-legacy",
                    "name": ".NET Core 2.x REST API",
                    "summary": "ASP.NET Core 2.x Web API with Startup-based hosting, running on IIS.",
                    "description": "REST API built on ASP.NET Core 2.0-2.2 using the classic Startup.cs ConfigureServices/Configure pair.",
                    "legacy_stack": ".NET Core 2.0 - 2.2",
                    "category": "web-api",
                    "typical_indicators": "Startup.cs with ConfigureServices/Configure, Program.cs with WebHost.CreateDefaultBuilder.",
                    "known_risks": "Default JSON serializer changes from Newtonsoft to System.Text.Json on modern .NET.",
                    "status": "active",
                }
            ]
        }
    )

    id: str = Field(
        description="Slug, lowercase and hyphenated. Immutable once created.", examples=["aspnetcore-rest-api-legacy"]
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
    # On the summary, not just the detail, so a caller can tell an
    # application pattern from a PROJECT_ROLE one without fetching each
    # pattern in turn. The retired pattern-validation's merge-target selector needed this:
    # merging a discovered shape into `role-library-project` is meaningless,
    # and filtering on an `id` prefix would be a convention masquerading as
    # a rule.
    classification_role: str = Field(description="PRIMARY, SECONDARY or PROJECT_ROLE.")
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
    detection_rules: dict = Field(description="Part C signal-rules/1.0 structure, evaluated by the classification engine.")
    typical_indicators: str | None = Field(description="Human-readable cues an engineer would notice.")
    known_risks: str | None = Field(description="Risks or gotchas worth knowing before migrating this pattern.")
    status: LifecycleStatus = Field(description="Lifecycle state: 'draft', 'active', or 'deprecated'.")
    version: int = Field(description="Increments on any material change (detection rules, name, legacy_stack, category).")
    classification_role: ClassificationRole = Field(description="'PRIMARY', 'SECONDARY', or 'PROJECT_ROLE'.")
    classification_family: str | None = Field(description="e.g. 'APPLICATION_TYPE', 'WEB_APPLICATION', 'CAPABILITY', 'PROJECT_ROLE'.")
    classification_value: str | None = Field(description="e.g. 'REST_API', 'WCF_SERVICE', 'TEST'.")
    scope: PatternScope = Field(description="'PROJECT' or 'REPOSITORY'. v1 evaluates PROJECT scope only.")
    priority: int = Field(description="Conflict tiebreak — higher wins.")
    compatible_with: list[str] = Field(description="Pattern ids this pattern may coexist with as a primary match.")
    conflicts_with: list[str] = Field(description="Pattern ids this pattern cannot coexist with as a primary match.")
    anchor_signals: list[str] = Field(description="Signal names used for the inverted candidate index.")
    eligibility: dict | None = Field(description="Fingerprint statuses and excluded project roles this pattern may be evaluated under.")
    analysis_requirements: dict | None = Field(description="Required vs preferred application-fingerprinting analysis capabilities.")
    thresholds: dict = Field(description="{minimumScore, highConfidenceScore} used by the classification engine.")
    rules_status: RulesStatus = Field(description="'active', 'awaiting_signals', or 'draft'. Only 'active' patterns are evaluated.")
    required_signals_pending: list[dict] = Field(
        description="Structured list of not-yet-registered signals this pattern's rules need."
    )
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
    target_framework: str = Field(
        default="net10.0",
        description="The .NET target framework moniker the estate moves to — what dependency-assessment checks every package against.",
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
    target_framework: str = Field(description="The .NET target framework moniker packages must support (dependency-assessment).")
    production_environment: str | None = Field(
        default=None,
        description="The environment whose host names a service in the endpoint register (dependency-and-context-map). "
        "Set through PUT /api/engagements/{id}/estate/settings.",
    )
    deploy_parameter_globs: list[str] | None = Field(
        default=None,
        description="Where Web Deploy SetParameters files are (application-fingerprinting and outbound-invocation-inventory); null means the defaults. "
        "Set through PUT /api/engagements/{id}/estate/settings.",
    )
    status: LifecycleStatus = Field(description="Lifecycle state: 'draft', 'active', or 'deprecated'.")
    created_at: datetime.datetime = Field(description="When this engagement was created.")
    updated_at: datetime.datetime = Field(description="When this engagement was last modified.")
    version: int = Field(default=1, description="Goes up with each edit of its settings. Send it back in If-Match: an edit made from a stale copy is refused.")
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
                    "perspective_breakdown": {"SECURITY": 1, "EVOLUTION": 1},
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
    perspective_breakdown: dict[str, int] = Field(
        description="Count of this engagement's non-superseded, non-deleted decisions per forcing_perspective — 25-STANDARDS-AND-VIEWPOINTS.md Part A1. Only perspectives with at least one decision appear."
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
                    "forcing_perspective": None,
                    "forcing_rationale": None,
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
    forcing_perspective: ForcingPerspective | None = Field(
        default=None,
        description="Required (with forcing_rationale) when the selection is not the lowest consumer_impact among candidates_considered — which quality concern forced the deviation.",
    )
    forcing_rationale: str | None = Field(
        default=None,
        description="Required (with forcing_perspective) when the selection is not the lowest consumer_impact among candidates_considered — the narrative explaining the deviation.",
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
                    "forcing_perspective": None,
                    "forcing_rationale": None,
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
    forcing_perspective: ForcingPerspective | None = Field(
        default=None,
        description="Required (with forcing_rationale) when the selection is not the lowest consumer_impact among candidates_considered.",
    )
    forcing_rationale: str | None = Field(
        default=None,
        description="Required (with forcing_perspective) when the selection is not the lowest consumer_impact among candidates_considered.",
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
    forcing_perspective: ForcingPerspective | None = Field(
        description="Which quality concern forced a higher-impact choice over the lift-and-shift default, if any."
    )
    forcing_rationale: str | None = Field(
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
    version: int = Field(default=1, description="Goes up with each edit. Send it back in If-Match: an edit made from a stale copy is refused.")


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
                    "pattern_id": "aspnetcore-rest-api-legacy",
                    "name": ".NET Core 2.x REST API",
                    "summary": "ASP.NET Core 2.x Web API with Startup-based hosting, running on IIS.",
                    "description": None,
                    "legacy_stack": ".NET Core 2.0 - 2.2",
                    "category": "web-api",
                    "detection_rules": {"schema": "signal-rules/1.0"},
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
                    "forcing_perspective": None,
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
    detection_rules: dict = Field(description="Master pattern's Part C signal-rules/1.0 structure.")
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
    forcing_perspective: ForcingPerspective | None = Field(
        description="The live decision's forcing perspective, if any was recorded."
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
                            "id": "aspnetcore-rest-api-legacy",
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
