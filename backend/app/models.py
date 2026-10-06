import datetime
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

LIFECYCLE_STATUS = ("draft", "active", "deprecated")
CONSUMER_IMPACT = ("none", "low", "medium", "high")
EFFORT = ("low", "medium", "high")
DECISION_STATUS = ("parked", "in_review", "approved", "superseded")
SCOPE_STATUS = ("active", "deferred")
# 25-STANDARDS-AND-VIEWPOINTS.md Part A1 — the quality concern that forced a
# higher-impact selection over the lift-and-shift default.
FORCING_PERSPECTIVE = (
    "SECURITY",
    "EVOLUTION",
    "REGULATION",
    "PERFORMANCE_SCALABILITY",
    "AVAILABILITY_RESILIENCE",
    "LOCATION",
    "DEVELOPMENT_RESOURCE",
)

# ---- Step 4 — pattern classification, catalog schema (24-STEP-004-CLASSIFICATION.md Part B1) ----
CLASSIFICATION_ROLE = ("PRIMARY", "SECONDARY", "PROJECT_ROLE")
PATTERN_SCOPE = ("PROJECT", "REPOSITORY")
RULES_STATUS = ("active", "awaiting_signals", "draft")
CATALOG_REVISION_ENTITY_TYPE = ("pattern", "target_state_option")
CATALOG_REVISION_OPERATION = ("insert", "update", "soft_delete")

# 25-STANDARDS-AND-VIEWPOINTS.md Part A2 — Rozanski & Woods. Nullable:
# governance and orchestration steps map to no viewpoint.
VIEWPOINT = (
    "CONTEXT",
    "FUNCTIONAL",
    "INFORMATION",
    "CONCURRENCY",
    "DEVELOPMENT",
    "DEPLOYMENT",
    "OPERATIONAL",
    "NONE",
)

ADAPTER_TYPE = ("python", "process", "http", "event", "stub")
# Combined codes (e.g. "P + S") denote shared authorship within one step and are
# stored verbatim — see 17-LIFECYCLE-STEPS.md "Owner codes". "C" is retired as a
# step owner (v2.0) and survives only on deprecated rows.
STEP_OWNER_CODE = ("P", "C", "S", "H", "P + S", "P + H")
IMPLEMENTATION_STATUS = ("stub", "implemented", "deprecated")
VALIDATION_STATUS = ("valid", "invalid")
BATCH_STATUS = (
    "STARTING",
    "STARTED",
    "COMPLETED",
    "FAILED",
    "STOPPING",
    "STOPPED",
    "ABANDONED",
    "UNKNOWN",
)
TRIGGERED_BY = ("manual", "api", "resume", "schedule")
# 22-STEP-SEQUENCING-AND-POLICY.md Part D, split per
# 23-WORKFLOW-ADMINISTRATION.md Part A: POLICY_DISABLED became
# POLICY_DISABLED_GLOBAL / POLICY_DISABLED_ENGAGEMENT so the timeline can say
# which layer disabled the step. Null unless exit_status is SKIPPED (enforced
# by ck_wf_step_executions_skip_reason_pairing below).
SKIP_REASON = (
    "POLICY_DISABLED_GLOBAL",
    "POLICY_DISABLED_ENGAGEMENT",
    "CONDITION_FALSE",
    "TIER_NOT_APPLICABLE",
    "UPSTREAM_SKIPPED",
    "CASCADED_POLICY",
)
CLONE_URL_VERIFICATION = ("verified", "mismatch", "unverifiable", "not_applicable")
SOURCE_TYPE = ("local_path", "git_clone")
CRITICALITY = ("low", "medium", "high", "critical")
RETIREMENT_STATUS = ("active", "slated_for_retirement", "decommissioned")
INGEST_STATUS = ("registered", "scanned", "scan_failed", "path_missing")
SOURCE_STATUS = ("active", "archived", "disabled", "inaccessible")
# Whether the registered folder is under git at all — distinct from
# source_status above (a provider-side lifecycle status, only ever knowable
# via a provider API). A legacy estate routinely contains folders that were
# never in source control (a file share, an old FTP drop); clone_url has no
# meaning for those. See 15-REPOSITORY-INGEST-UI.md Part C.
SOURCE_CONTROL_STATUS = ("GIT", "NONE")

# ---- Step 2 — solution & project discovery (19-STEP-002-SOLUTION-DISCOVERY.md) ----
SCAN_STATUS = ("complete", "partial", "failed")
PARSE_STATUS = ("success", "partial", "failed", "out_of_scope")
PROJECT_FORMAT = ("legacy_msbuild", "sdk_style", "unknown")
PROJECT_LANGUAGE = ("csharp", "vb", "fsharp", "sql", "ssis", "cpp", "shared", "unknown")
SOLUTION_PROJECT_RESOLUTION_STATUS = ("resolved", "unresolved")
PROJECT_REFERENCE_RESOLUTION_STATUS = ("resolved", "unresolved", "external_repository")
PACKAGE_DECLARATION_SOURCE = ("packagereference", "packages_config")
PACKAGE_MANAGEMENT_STYLE = ("packagereference", "packages_config", "mixed", "none")
REPOSITORY_ARTIFACT_CATEGORY = (
    "build",
    "package",
    "pipeline",
    "container",
    "script",
    "configuration",
    "deployment",
    "documentation",
)

# ---- Step 3 — application fingerprinting (21-STEP-003-FINGERPRINTING.md Part E) ----
FINGERPRINT_STATUS = ("complete", "partial", "failed", "skipped", "not_supported")
# The sixteen categories from step-3-application-fingerprinting.md section 19,
# SCREAMING_SNAKE_CASE per 21-STEP-003-FINGERPRINTING.md Part D. Renaming any of
# these later means rewriting every signal registry entry and catalog detection
# rule that references it — see that doc's note on step 4.
SIGNAL_CATEGORY = (
    "PROJECT_METADATA",
    "FRAMEWORK_REFERENCE",
    "PACKAGE_DEPENDENCY",
    "SOURCE_CONSTRUCT",
    "FILE_INDICATOR",
    "CONFIGURATION_INDICATOR",
    "ENTRY_POINT",
    "ENDPOINT_INDICATOR",
    "EXECUTION_INDICATOR",
    "HOSTING_INDICATOR",
    "UI_INDICATOR",
    "DATA_ACCESS_INDICATOR",
    "MESSAGING_INDICATOR",
    "SCHEDULING_INDICATOR",
    "DEPLOYMENT_INDICATOR",
    "TESTING_INDICATOR",
)
SIGNAL_TYPE = (
    "ATTRIBUTE",
    "BASE_CLASS",
    "FILE_PRESENCE",
    "INVOCATION",
    "CONFIG_ELEMENT",
    "PACKAGE",
    "ASSEMBLY",
    "NAMESPACE",
    "ROUTE",
    "ENTRY_POINT",
    # 21-STEP-003-FINGERPRINTING.md Part D "Signal types" — added with
    # application-fingerprint@1.2.0. API_INVOCATION: use of a specific member
    # (DateTime.Now). LITERAL: a source or config value matching a pattern (a
    # Windows path); its evidence carries matchedValue.
    "API_INVOCATION",
    "LITERAL",
)

# The nine source types from step-3-application-fingerprinting.md section 18.
EVIDENCE_SOURCE_TYPE = (
    "PROJECT_FILE",
    "SOURCE_CODE",
    "CONFIGURATION",
    "FILE_STRUCTURE",
    "PACKAGE_REFERENCE",
    "ASSEMBLY_REFERENCE",
    "PIPELINE",
    "DEPLOYMENT_SCRIPT",
    "SOLUTION_METADATA",
)

# What source_path names — from the signal registry's evidence_kind field
# (25-STANDARDS-AND-VIEWPOINTS.md Part A3 addendum). FOLDER and NONE must
# never be treated as an openable file location by any consumer of
# fingerprint_signals (e.g. a future "view evidence" UI) — that assumption is
# exactly what broke the step 3 SARIF viewer.
SIGNAL_EVIDENCE_KIND = ("FILE", "FOLDER", "NONE")


class Pattern(Base):
    __tablename__ = "patterns"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    legacy_stack: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    detection_rules: Mapped[dict] = mapped_column(JSONB, nullable=False)
    typical_indicators: Mapped[str | None] = mapped_column(Text)
    known_risks: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    # ---- Step 4 classification schema (24-STEP-004-CLASSIFICATION.md Part B1) ----
    # `detection_rules` holds the Part C signal-rules/1.0 structure. The
    # pre-step-4 tag-input rules this superseded lived in
    # `detection_rules_legacy` through J1-J4's transition; dropped once the
    # rule builder (J4) was verified (Part B4).
    classification_role: Mapped[str] = mapped_column(Text, nullable=False, server_default="PRIMARY")
    classification_family: Mapped[str | None] = mapped_column(Text)
    classification_value: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text, nullable=False, server_default="PROJECT")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50")
    compatible_with: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    conflicts_with: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    anchor_signals: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    eligibility: Mapped[dict | None] = mapped_column(JSONB)
    analysis_requirements: Mapped[dict | None] = mapped_column(JSONB)
    thresholds: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default='{"minimumScore": 70, "highConfidenceScore": 90}'
    )
    rules_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    required_signals_pending: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            f"status IN {LIFECYCLE_STATUS}", name="ck_patterns_status"
        ),
        CheckConstraint(
            f"classification_role IN {CLASSIFICATION_ROLE}", name="ck_patterns_classification_role"
        ),
        CheckConstraint(f"scope IN {PATTERN_SCOPE}", name="ck_patterns_scope"),
        CheckConstraint(f"rules_status IN {RULES_STATUS}", name="ck_patterns_rules_status"),
        Index("ix_patterns_status", "status"),
        Index("ix_patterns_category", "category"),
        Index("ix_patterns_not_deleted", "id", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_patterns_rules_status", "rules_status"),
    )


class TargetStateOption(Base):
    __tablename__ = "target_state_options"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    pattern_id: Mapped[str] = mapped_column(
        Text, ForeignKey("patterns.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    target_stack: Mapped[str] = mapped_column(Text, nullable=False)
    consumer_impact: Mapped[str] = mapped_column(Text, nullable=False)
    effort: Mapped[str] = mapped_column(Text, nullable=False)
    linux_compatible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    container_ready: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    is_lift_and_shift: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_recommended: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    engine_support: Mapped[dict | None] = mapped_column(JSONB)
    playbook_md: Mapped[str | None] = mapped_column(Text)
    prerequisites: Mapped[str | None] = mapped_column(Text)
    known_limitations: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("pattern_id", "name", name="uq_target_state_options_pattern_name"),
        CheckConstraint(
            f"status IN {LIFECYCLE_STATUS}", name="ck_target_state_options_status"
        ),
        CheckConstraint(
            f"consumer_impact IN {CONSUMER_IMPACT}",
            name="ck_target_state_options_consumer_impact",
        ),
        CheckConstraint(f"effort IN {EFFORT}", name="ck_target_state_options_effort"),
        Index("ix_target_state_options_pattern_id", "pattern_id"),
        Index("ix_target_state_options_status", "status"),
        Index(
            "ix_target_state_options_not_deleted", "id", postgresql_where=text("deleted_at IS NULL")
        ),
    )


class CatalogRevision(Base):
    """One row per mutating write to `patterns` or `target_state_options`.
    The current catalog revision is `MAX(id)` — a monotonic integer that never
    goes backwards, since nothing here is ever hard-deleted. Recorded on every
    classification (step 4) so a result can always be traced back to the exact
    catalog state that produced it (24-STEP-004-CLASSIFICATION.md Part H)."""

    __tablename__ = "catalog_revisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            f"entity_type IN {CATALOG_REVISION_ENTITY_TYPE}", name="ck_catalog_revisions_entity_type"
        ),
        CheckConstraint(
            f"operation IN {CATALOG_REVISION_OPERATION}", name="ck_catalog_revisions_operation"
        ),
        Index("ix_catalog_revisions_entity", "entity_type", "entity_id"),
    )


class Engagement(Base):
    __tablename__ = "engagements"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    client_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    target_platform: Mapped[str | None] = mapped_column(Text)
    default_posture: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="lift-and-shift"
    )
    # Step 6 (30-STEP-006 Part C1): the framework packages must support.
    target_framework: Mapped[str] = mapped_column(Text, nullable=False, server_default="net10.0")
    # Step 11 (31-STEP-011 Part C1): the environment whose host names a
    # service in the endpoint register. Null: group by the host as found.
    production_environment: Mapped[str | None] = mapped_column(Text)
    # Step 5 (29-STEPS Part C9, 1.3.0): globs for Web Deploy SetParameters
    # files. Null means **/SetParam*.xml and **/SetParameters*.xml.
    deploy_parameter_globs: Mapped[list | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(f"status IN {LIFECYCLE_STATUS}", name="ck_engagements_status"),
    )


class DecisionRecord(Base):
    __tablename__ = "decision_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    engagement_id: Mapped[str] = mapped_column(
        Text, ForeignKey("engagements.id"), nullable=False
    )
    pattern_id: Mapped[str] = mapped_column(
        Text, ForeignKey("patterns.id"), nullable=False
    )
    selected_target_state_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("target_state_options.id")
    )
    candidates_considered: Mapped[list | None] = mapped_column(JSONB)
    evaluation_notes: Mapped[str | None] = mapped_column(Text)
    forcing_perspective: Mapped[str | None] = mapped_column(Text)
    forcing_rationale: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    approver_name: Mapped[str | None] = mapped_column(Text)
    approver_role: Mapped[str | None] = mapped_column(Text)
    decision_date: Mapped[datetime.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="parked")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            f"status IN {DECISION_STATUS}", name="ck_decision_records_status"
        ),
        CheckConstraint(
            f"forcing_perspective IS NULL OR forcing_perspective IN {FORCING_PERSPECTIVE}",
            name="ck_decision_records_forcing_perspective",
        ),
        Index("ix_decision_records_engagement_id", "engagement_id"),
        Index("ix_decision_records_pattern_id", "pattern_id"),
        Index("ix_decision_records_status", "status"),
        Index(
            "uq_decision_records_live_per_pattern",
            "engagement_id",
            "pattern_id",
            unique=True,
            postgresql_where=text("status <> 'superseded' AND deleted_at IS NULL"),
        ),
    )


class EngagementPattern(Base):
    """The client-scoped overlay on a master pattern. Lazy: absence of a row
    means active and not deleted for that engagement — see 02-DATA-MODEL.md."""

    __tablename__ = "engagement_patterns"

    engagement_id: Mapped[str] = mapped_column(
        Text, ForeignKey("engagements.id"), primary_key=True
    )
    pattern_id: Mapped[str] = mapped_column(
        Text, ForeignKey("patterns.id"), primary_key=True
    )
    scope_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    deferred_reason: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"scope_status IN {SCOPE_STATUS}", name="ck_engagement_patterns_scope_status"),
        Index("ix_engagement_patterns_engagement_id", "engagement_id"),
        Index("ix_engagement_patterns_engagement_scope_status", "engagement_id", "scope_status"),
    )


class StepPolicy(Base):
    """One policy row, at either the global or engagement layer — see
    23-WORKFLOW-ADMINISTRATION.md Part A. `engagement_id IS NULL` means
    global ("nobody should run this yet"); a non-null `engagement_id` means
    a client-specific override ("this client does not want this").
    Precedence is engagement beats global beats default (absence of any row).
    This table only ever holds deviations from default, so a newly
    registered step needs no backfill."""

    __tablename__ = "step_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # Null means global — a row scoped to every engagement at once, not to
    # one in particular.
    engagement_id: Mapped[str | None] = mapped_column(Text, ForeignKey("engagements.id"), nullable=True)
    step_name: Mapped[str] = mapped_column(
        Text, ForeignKey("wf_step_registrations.step_name"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # Required in either direction (Part A): "why is this step running for
    # Client A when it is globally off" needs an answer as much as the
    # reverse. A cascade-created row's reason is always the literal
    # "cascaded from disabling <step_name>" — the runtime distinguishes
    # skip_reason CASCADED_POLICY from POLICY_DISABLED_GLOBAL /
    # POLICY_DISABLED_ENGAGEMENT by that convention rather than a separate
    # column (spec documents no such column).
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    set_by: Mapped[str | None] = mapped_column(Text)
    set_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # A plain UNIQUE(engagement_id, step_name) would treat every NULL
        # engagement_id as distinct, allowing duplicate global rows — two
        # partial indexes instead, one per layer.
        Index(
            "uq_step_policies_global_step",
            "step_name",
            unique=True,
            postgresql_where=text("engagement_id IS NULL"),
        ),
        Index(
            "uq_step_policies_engagement_step",
            "engagement_id",
            "step_name",
            unique=True,
            postgresql_where=text("engagement_id IS NOT NULL"),
        ),
        Index("ix_step_policies_engagement_id", "engagement_id"),
    )


class WfStepRegistration(Base):
    """The registry of known engine steps — see 10-ENGINE-CONCEPTS.md."""

    __tablename__ = "wf_step_registrations"

    step_name: Mapped[str] = mapped_column(Text, primary_key=True)
    lifecycle_step_no: Mapped[int | None] = mapped_column(Integer)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    owner_code: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    adapter_type: Mapped[str] = mapped_column(Text, nullable=False)
    adapter_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    consumes: Mapped[list] = mapped_column(JSONB, nullable=False)
    produces: Mapped[list] = mapped_column(JSONB, nullable=False)
    implementation_status: Mapped[str] = mapped_column(Text, nullable=False)
    owner_team: Mapped[str | None] = mapped_column(Text)
    viewpoint: Mapped[str | None] = mapped_column(Text)
    # Soft delete = the slug was renamed (the step lives on under
    # `superseded_by`); the row leaves the step list but still resolves by
    # name for wf_step_executions history. Distinct from
    # implementation_status 'deprecated', which means the step left the
    # lifecycle and stays listed. See migration e5c1d7a93f20.
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(Text)
    # Plain text pointer, not an FK: a retired row may point at a v2 step
    # that is registered later.
    superseded_by: Mapped[str | None] = mapped_column(Text)
    retired_reason: Mapped[str | None] = mapped_column(Text)
    registered_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"owner_code IN {STEP_OWNER_CODE}", name="ck_wf_step_registrations_owner_code"),
        # 'C' stays in STEP_OWNER_CODE only so deprecated rows keep their
        # true historical owner — no live step is owned by an engine
        # (17-LIFECYCLE-STEPS.md v2.0 "Owner codes").
        CheckConstraint(
            "owner_code <> 'C' OR implementation_status = 'deprecated'",
            name="ck_wf_step_registrations_no_engine_owner",
        ),
        CheckConstraint(f"adapter_type IN {ADAPTER_TYPE}", name="ck_wf_step_registrations_adapter_type"),
        CheckConstraint(
            f"implementation_status IN {IMPLEMENTATION_STATUS}",
            name="ck_wf_step_registrations_implementation_status",
        ),
        CheckConstraint(
            f"viewpoint IS NULL OR viewpoint IN {VIEWPOINT}", name="ck_wf_step_registrations_viewpoint"
        ),
    )


class WfJobDefinition(Base):
    __tablename__ = "wf_job_definitions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    job_name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # The exact YAML text this row was stored from — for the job definition
    # viewer's "Raw YAML" panel (22-STEP-SEQUENCING-AND-POLICY.md Part E).
    # Nullable only because rows stored before this column existed have none.
    source_yaml: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    validation_status: Mapped[str] = mapped_column(Text, nullable=False)
    validation_errors: Mapped[list | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("job_name", "version", name="uq_wf_job_definitions_job_name_version"),
        CheckConstraint(
            f"validation_status IN {VALIDATION_STATUS}", name="ck_wf_job_definitions_validation_status"
        ),
        Index(
            "uq_wf_job_definitions_active_job_name",
            "job_name",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )


class WfJobInstance(Base):
    __tablename__ = "wf_job_instances"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    job_name: Mapped[str] = mapped_column(Text, nullable=False)
    job_key: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("job_name", "job_key", name="uq_wf_job_instances_job_name_job_key"),
    )


class WfJobExecution(Base):
    __tablename__ = "wf_job_executions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    job_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wf_job_instances.id"), nullable=False
    )
    job_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wf_job_definitions.id"), nullable=False
    )
    execution_number: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_status: Mapped[str] = mapped_column(Text, nullable=False)
    exit_status: Mapped[str | None] = mapped_column(Text)
    exit_message: Mapped[str | None] = mapped_column(Text)
    execution_context: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"batch_status IN {BATCH_STATUS}", name="ck_wf_job_executions_batch_status"),
        CheckConstraint(
            f"triggered_by IS NULL OR triggered_by IN {TRIGGERED_BY}",
            name="ck_wf_job_executions_triggered_by",
        ),
    )


class WfStepExecution(Base):
    __tablename__ = "wf_step_executions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    job_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wf_job_executions.id"), nullable=False
    )
    step_name: Mapped[str] = mapped_column(Text, nullable=False)
    step_version: Mapped[str] = mapped_column(Text, nullable=False)
    partition_key: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    batch_status: Mapped[str] = mapped_column(Text, nullable=False)
    exit_status: Mapped[str | None] = mapped_column(Text)
    exit_message: Mapped[str | None] = mapped_column(Text)
    skip_reason: Mapped[str | None] = mapped_column(Text)
    read_count: Mapped[int] = mapped_column(Integer, server_default="0")
    write_count: Mapped[int] = mapped_column(Integer, server_default="0")
    skip_count: Mapped[int] = mapped_column(Integer, server_default="0")
    commit_count: Mapped[int] = mapped_column(Integer, server_default="0")
    execution_context: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    diagnostics: Mapped[list | None] = mapped_column(JSONB)
    inputs_resolved: Mapped[list | None] = mapped_column(JSONB)
    stdout_tail: Mapped[str | None] = mapped_column(Text)
    stderr_tail: Mapped[str | None] = mapped_column(Text)
    carried_forward: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    working_dir: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"batch_status IN {BATCH_STATUS}", name="ck_wf_step_executions_batch_status"),
        CheckConstraint(f"skip_reason IS NULL OR skip_reason IN {SKIP_REASON}", name="ck_wf_step_executions_skip_reason"),
        CheckConstraint(
            "skip_reason IS NULL OR exit_status = 'SKIPPED'",
            name="ck_wf_step_executions_skip_reason_pairing",
        ),
        Index("ix_wf_step_executions_job_execution_id_step_name", "job_execution_id", "step_name"),
    )


class WfArtifact(Base):
    __tablename__ = "wf_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    step_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wf_step_executions.id"), nullable=False
    )
    job_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wf_job_executions.id"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_version: Mapped[str] = mapped_column(Text, nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    artifact_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_wf_artifacts_job_execution_id_artifact_type", "job_execution_id", "artifact_type"),
    )


class Repository(Base):
    """Registered local repository for phase 0 discovery — see
    15-REPOSITORY-INGEST-UI.md Part C. Replaces the definition in
    13-STEP-001-REPOSITORY-INGEST.md."""

    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    engagement_id: Mapped[str] = mapped_column(Text, ForeignKey("engagements.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    root_folder_name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    local_path_normalised: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable — a folder that was never under source control has no
    # canonical URL to assert. Required only when source_control_status is
    # GIT; see ck_repositories_clone_url_required_for_git below.
    clone_url: Mapped[str | None] = mapped_column(Text)
    clone_url_normalised: Mapped[str | None] = mapped_column(Text)
    detected_clone_url: Mapped[str | None] = mapped_column(Text)
    clone_url_verification: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="unverifiable"
    )
    # GIT when the folder has a .git directory, NONE otherwise. Re-derived on
    # every scan (repository_ingest.py), not just at registration — a folder
    # can be migrated into source control after being registered.
    source_control_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="NONE")
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(Text)
    default_branch: Mapped[str | None] = mapped_column(Text)

    description: Mapped[str | None] = mapped_column(Text)
    technical_owner: Mapped[str | None] = mapped_column(Text)
    criticality: Mapped[str] = mapped_column(Text, nullable=False, server_default="medium")
    retirement_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    notes: Mapped[str | None] = mapped_column(Text)

    has_git_history: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    ingest_commit_sha: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    file_count: Mapped[int | None] = mapped_column(Integer)
    ingest_status: Mapped[str] = mapped_column(Text, nullable=False)
    ingest_error: Mapped[str | None] = mapped_column(Text)
    ingest_token: Mapped[str | None] = mapped_column(Text)

    # docs/19 Part A — step 1 amendments feeding step 2's requirements.
    organization: Mapped[str | None] = mapped_column(Text)
    last_commit_date: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    primary_languages: Mapped[list | None] = mapped_column(JSONB)
    # Source-control platform status — only knowable via a provider API, so
    # always null for local_path. Deliberately distinct from ingest_status
    # (did our scan work?) and retirement_status (in modernization scope?).
    source_status: Mapped[str | None] = mapped_column(Text)

    first_registered_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    last_scanned_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            f"clone_url_verification IN {CLONE_URL_VERIFICATION}",
            name="ck_repositories_clone_url_verification",
        ),
        CheckConstraint(
            f"source_control_status IN {SOURCE_CONTROL_STATUS}",
            name="ck_repositories_source_control_status",
        ),
        CheckConstraint(
            "source_control_status != 'GIT' OR clone_url IS NOT NULL",
            name="ck_repositories_clone_url_required_for_git",
        ),
        CheckConstraint(f"source_type IN {SOURCE_TYPE}", name="ck_repositories_source_type"),
        CheckConstraint(f"criticality IN {CRITICALITY}", name="ck_repositories_criticality"),
        CheckConstraint(
            f"retirement_status IN {RETIREMENT_STATUS}", name="ck_repositories_retirement_status"
        ),
        CheckConstraint(f"ingest_status IN {INGEST_STATUS}", name="ck_repositories_ingest_status"),
        CheckConstraint(
            f"source_status IS NULL OR source_status IN {SOURCE_STATUS}",
            name="ck_repositories_source_status",
        ),
        Index(
            "uq_repositories_engagement_clone_url_normalised",
            "engagement_id",
            "clone_url_normalised",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND clone_url_normalised IS NOT NULL"),
        ),
        Index(
            "uq_repositories_engagement_root_folder_name",
            "engagement_id",
            "root_folder_name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_repositories_engagement_local_path_normalised",
            "engagement_id",
            "local_path_normalised",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_repositories_engagement_id", "engagement_id"),
        Index("ix_repositories_ingest_status", "ingest_status"),
        Index("ix_repositories_retirement_status", "retirement_status"),
    )


class RepositoryStructure(Base):
    """1:1 summary written by step 2 (solution-discovery). Separate from
    `repositories` so step ownership is explicit and replacement — delete by
    repository_id, then insert — is trivial. See
    19-STEP-002-SOLUTION-DISCOVERY.md Part C."""

    __tablename__ = "repository_structure"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    scan_status: Mapped[str] = mapped_column(Text, nullable=False)
    solution_count: Mapped[int | None] = mapped_column(Integer)
    project_file_count: Mapped[int | None] = mapped_column(Integer)
    projects_referenced_count: Mapped[int | None] = mapped_column(Integer)
    standalone_project_count: Mapped[int | None] = mapped_column(Integer)
    shared_project_count: Mapped[int | None] = mapped_column(Integer)
    unresolved_reference_count: Mapped[int | None] = mapped_column(Integer)
    out_of_scope_project_count: Mapped[int | None] = mapped_column(Integer)
    unknown_project_count: Mapped[int | None] = mapped_column(Integer)
    failed_parse_count: Mapped[int | None] = mapped_column(Integer)
    legacy_project_count: Mapped[int | None] = mapped_column(Integer)
    sdk_project_count: Mapped[int | None] = mapped_column(Integer)
    framework_families: Mapped[dict | None] = mapped_column(JSONB)
    artifact_counts: Mapped[dict | None] = mapped_column(JSONB)
    parse_warnings: Mapped[list | None] = mapped_column(JSONB)
    step_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    scanned_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"scan_status IN {SCAN_STATUS}", name="ck_repository_structure_scan_status"),
    )


class Solution(Base):
    """A `.sln` file found on disk. See 19-STEP-002-SOLUTION-DISCOVERY.md Part C."""

    __tablename__ = "solutions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    format_version: Mapped[str | None] = mapped_column(Text)
    visual_studio_version: Mapped[str | None] = mapped_column(Text)
    minimum_vs_version: Mapped[str | None] = mapped_column(Text)
    project_count: Mapped[int | None] = mapped_column(Integer)
    resolved_project_count: Mapped[int | None] = mapped_column(Integer)
    missing_project_count: Mapped[int | None] = mapped_column(Integer)
    solution_folder_count: Mapped[int | None] = mapped_column(Integer)
    shared_project_count: Mapped[int | None] = mapped_column(Integer)
    parse_status: Mapped[str] = mapped_column(Text, nullable=False)
    parse_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("repository_id", "relative_path", name="uq_solutions_repository_relative_path"),
        CheckConstraint(f"parse_status IN {PARSE_STATUS}", name="ck_solutions_parse_status"),
        Index("ix_solutions_repository_id", "repository_id"),
    )


class Project(Base):
    """A project file (`.csproj`, `.vbproj`, ...) found on disk. Raw metadata
    only — no interpretation. See 19-STEP-002-SOLUTION-DISCOVERY.md Parts C/D/E."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    extension: Mapped[str] = mapped_column(Text, nullable=False)
    structural_type: Mapped[str] = mapped_column(Text, nullable=False)
    project_format: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    assembly_name: Mapped[str | None] = mapped_column(Text)
    root_namespace: Mapped[str | None] = mapped_column(Text)
    output_type: Mapped[str | None] = mapped_column(Text)
    # Step 2 (solution-project-inventory 2.1.0): the SDK the project file
    # declares, version stripped; 'none' for a legacy MSBuild project.
    project_sdk: Mapped[str | None] = mapped_column(Text)
    target_framework_raw: Mapped[str | None] = mapped_column(Text)
    target_frameworks_raw: Mapped[list | None] = mapped_column(JSONB)
    framework_family: Mapped[str | None] = mapped_column(Text)
    framework_version: Mapped[str | None] = mapped_column(Text)
    is_multi_targeting: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    solution_membership_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_standalone: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    project_reference_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    package_reference_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    package_management_style: Mapped[str] = mapped_column(Text, nullable=False)
    has_packages_config: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    parse_status: Mapped[str] = mapped_column(Text, nullable=False)
    parse_warnings: Mapped[list | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("repository_id", "relative_path", name="uq_projects_repository_relative_path"),
        CheckConstraint(f"project_format IN {PROJECT_FORMAT}", name="ck_projects_project_format"),
        CheckConstraint(f"language IN {PROJECT_LANGUAGE}", name="ck_projects_language"),
        CheckConstraint(
            f"package_management_style IN {PACKAGE_MANAGEMENT_STYLE}",
            name="ck_projects_package_management_style",
        ),
        CheckConstraint(f"parse_status IN {PARSE_STATUS}", name="ck_projects_parse_status"),
        Index("ix_projects_repository_id", "repository_id"),
        Index("ix_projects_repository_framework_family", "repository_id", "framework_family"),
        Index("ix_projects_repository_project_format", "repository_id", "project_format"),
    )


class SolutionProject(Base):
    """Solution membership — one row per `.sln` project entry (excluding
    solution-folder entries). See 19-STEP-002-SOLUTION-DISCOVERY.md Part C."""

    __tablename__ = "solution_projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    solution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("solutions.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    raw_path: Mapped[str] = mapped_column(Text, nullable=False)
    project_guid: Mapped[str | None] = mapped_column(Text)
    project_type_guid: Mapped[str | None] = mapped_column(Text)
    solution_folder: Mapped[str | None] = mapped_column(Text)
    resolution_status: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("solution_id", "raw_path", name="uq_solution_projects_solution_raw_path"),
        CheckConstraint(
            f"resolution_status IN {SOLUTION_PROJECT_RESOLUTION_STATUS}",
            name="ck_solution_projects_resolution_status",
        ),
        Index("ix_solution_projects_solution_id", "solution_id"),
        Index("ix_solution_projects_project_id", "project_id"),
    )


class ProjectReference(Base):
    """A `<ProjectReference>` declaration. See
    19-STEP-002-SOLUTION-DISCOVERY.md Part C."""

    __tablename__ = "project_references"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    source_project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    referenced_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    raw_path: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_status: Mapped[str] = mapped_column(Text, nullable=False)
    is_cross_solution: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        UniqueConstraint("source_project_id", "raw_path", name="uq_project_references_source_raw_path"),
        CheckConstraint(
            f"resolution_status IN {PROJECT_REFERENCE_RESOLUTION_STATUS}",
            name="ck_project_references_resolution_status",
        ),
        Index("ix_project_references_source_project_id", "source_project_id"),
        Index("ix_project_references_referenced_project_id", "referenced_project_id"),
    )


class ProjectPackage(Base):
    """A NuGet package declaration — `<PackageReference>` or a
    `packages.config` entry. See 19-STEP-002-SOLUTION-DISCOVERY.md Part C."""

    __tablename__ = "project_packages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    package_name: Mapped[str] = mapped_column(Text, nullable=False)
    version_raw: Mapped[str | None] = mapped_column(Text)
    declaration_source: Mapped[str] = mapped_column(Text, nullable=False)
    target_framework_raw: Mapped[str | None] = mapped_column(Text)
    is_malformed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        UniqueConstraint(
            "project_id", "package_name", "declaration_source", name="uq_project_packages_project_name_source"
        ),
        CheckConstraint(
            f"declaration_source IN {PACKAGE_DECLARATION_SOURCE}", name="ck_project_packages_declaration_source"
        ),
        Index("ix_project_packages_project_id", "project_id"),
    )


class RepositoryArtifact(Base):
    """Presence-only record of a supporting file (build config, pipeline
    definition, container file, ...). No content interpretation. See
    19-STEP-002-SOLUTION-DISCOVERY.md Part C."""

    __tablename__ = "repository_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(Text, nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("repository_id", "relative_path", name="uq_repository_artifacts_repository_relative_path"),
        CheckConstraint(f"category IN {REPOSITORY_ARTIFACT_CATEGORY}", name="ck_repository_artifacts_category"),
        Index("ix_repository_artifacts_repository_id", "repository_id"),
    )


class ProjectFingerprint(Base):
    """1:1 with `projects` — written by step 3 (application-fingerprinting).
    Replaced wholesale per repository on rescan, same pattern as
    `repository_structure` for step 2. See
    21-STEP-003-FINGERPRINTING.md Part E."""

    __tablename__ = "project_fingerprints"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    fingerprint_status: Mapped[str] = mapped_column(Text, nullable=False)
    scanner_version: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_capabilities: Mapped[dict] = mapped_column(JSONB, nullable=False)
    project_sdk: Mapped[str | None] = mapped_column(Text)
    nullable_enabled: Mapped[bool | None] = mapped_column(Boolean)
    implicit_usings: Mapped[bool | None] = mapped_column(Boolean)
    evaluated_properties: Mapped[dict | None] = mapped_column(JSONB)
    signal_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    category_summary: Mapped[dict | None] = mapped_column(JSONB)
    warnings: Mapped[list | None] = mapped_column(JSONB)
    analysis_duration_ms: Mapped[int | None] = mapped_column(Integer)
    step_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    fingerprinted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"fingerprint_status IN {FINGERPRINT_STATUS}", name="ck_project_fingerprints_status"),
        Index("ix_project_fingerprints_repository_id", "repository_id"),
    )


class FingerprintSignal(Base):
    """One row per `(project, signal_name, source_path)` — aggregated, not
    per-occurrence; `occurrence_count` carries the true total and `evidence`
    is capped at 20 entries. `project_id` is null for repository-level
    signals. See 21-STEP-003-FINGERPRINTING.md Part E."""

    __tablename__ = "fingerprint_signals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    signal_name: Mapped[str] = mapped_column(Text, nullable=False)
    signal_category: Mapped[str] = mapped_column(Text, nullable=False)
    signal_type: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_path: Mapped[str | None] = mapped_column(Text)
    evidence_kind: Mapped[str | None] = mapped_column(Text)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    evidence: Mapped[list | None] = mapped_column(JSONB)
    extractor: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)

    __table_args__ = (
        CheckConstraint(f"signal_category IN {SIGNAL_CATEGORY}", name="ck_fingerprint_signals_category"),
        CheckConstraint(f"signal_type IN {SIGNAL_TYPE}", name="ck_fingerprint_signals_type"),
        CheckConstraint(f"source_type IN {EVIDENCE_SOURCE_TYPE}", name="ck_fingerprint_signals_source_type"),
        CheckConstraint(
            f"evidence_kind IS NULL OR evidence_kind IN {SIGNAL_EVIDENCE_KIND}",
            name="ck_fingerprint_signals_evidence_kind",
        ),
        Index(
            "uq_fingerprint_signals_project_scope",
            "project_id",
            "signal_name",
            "source_path",
            "value",
            unique=True,
            postgresql_where=text("project_id IS NOT NULL"),
        ),
        Index(
            "uq_fingerprint_signals_repository_scope",
            "repository_id",
            "signal_name",
            "source_path",
            "value",
            unique=True,
            postgresql_where=text("project_id IS NULL"),
        ),
        Index("ix_fingerprint_signals_repository_signal_name", "repository_id", "signal_name"),
        Index("ix_fingerprint_signals_repository_signal_category", "repository_id", "signal_category"),
    )


class FingerprintScan(Base):
    """1:1 with `repositories` — the repository-level summary written by
    step 3 (application-fingerprinting). See 21-STEP-003-FINGERPRINTING.md
    Part E."""

    __tablename__ = "fingerprint_scans"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    scan_status: Mapped[str] = mapped_column(Text, nullable=False)
    scanner_version: Mapped[str] = mapped_column(Text, nullable=False)
    signal_registry_version: Mapped[str] = mapped_column(Text, nullable=False)
    projects_eligible: Mapped[int | None] = mapped_column(Integer)
    projects_complete: Mapped[int | None] = mapped_column(Integer)
    projects_partial: Mapped[int | None] = mapped_column(Integer)
    projects_failed: Mapped[int | None] = mapped_column(Integer)
    projects_skipped: Mapped[int | None] = mapped_column(Integer)
    total_signals: Mapped[int | None] = mapped_column(Integer)
    total_evidence: Mapped[int | None] = mapped_column(Integer)
    semantic_analysis_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    repository_signal_count: Mapped[int | None] = mapped_column(Integer)
    warnings: Mapped[list | None] = mapped_column(JSONB)
    step_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    scanned_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"scan_status IN {SCAN_STATUS}", name="ck_fingerprint_scans_scan_status"),
    )


class ValidationQueueItem(Base):
    """One thing a human must decide — 27-STEP-006-PATTERN-VALIDATION.md
    Part B.

    **Generic across every gate step**, not step 6's own table. Step 6 is
    the first consumer; steps 22 (plan approval), 38 (code review) and 50
    (release approval) raise items here too. Everything step-specific
    lives in `item_type` and `payload`, so a new gate needs no schema
    change and inherits the queue UI, the summary and the decide/defer
    endpoints as they stand.
    """

    __tablename__ = "validation_queue"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    engagement_id: Mapped[str] = mapped_column(
        Text, ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    job_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wf_job_executions.id", ondelete="CASCADE"), nullable=False
    )
    step_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wf_step_executions.id", ondelete="CASCADE"), nullable=False
    )
    step_name: Mapped[str] = mapped_column(Text, nullable=False)
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    item_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    outcome: Mapped[str | None] = mapped_column(Text)
    outcome_detail: Mapped[dict | None] = mapped_column(JSONB)
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    # A deferred item keeps status 'open' — the subject still needs an
    # answer — but is set aside until the evidence improves.
    deferred_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deferred_until_coverage: Mapped[float | None] = mapped_column(Numeric(4, 3))
    deferred_until_member_count: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Created by migration d8f3a15c72be; declared here so the model matches
    # the database (alembic check reported them as drift until they were).
    __table_args__ = (
        # At most one open item per subject; closed ones accumulate freely.
        Index(
            "uq_validation_queue_open_item",
            "engagement_id",
            "step_name",
            "item_key",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_validation_queue_engagement_status", "engagement_id", "status"),
        Index("ix_validation_queue_job_execution", "job_execution_id"),
        Index("ix_validation_queue_status_priority", "status", "priority"),
    )

    @property
    def is_deferred(self) -> bool:
        return self.status == "open" and self.deferred_at is not None


# ---- Item & conversion model, catalog half (28-ITEM-AND-CONVERSION-MODEL.md Parts C-G) ----
# Built ALONGSIDE the pattern tables above, which stay untouched until the
# new model has been verified against the old (Part Q "run both models side
# by side"). Nothing here references `patterns`, `target_state_options`,
# `decision_records` or `engagement_patterns`.

READINESS_STATE = ("ready", "not_ready")
EXTRACTOR_STATUS = ("implemented", "planned")
ITEM_SCOPE = ("application", "occurrence")
ITEM_CATEGORY = (
    "hosting",
    "logging",
    "configuration",
    "security",
    "data-access",
    "integration",
    "packaging",
    "dependencies",
    "framework",
)
# Master catalog lifecycle, distinct from computed readiness `state` and from
# soft delete — CLAUDE.md rule 7.
ITEM_STATUS = ("active", "deprecated")
ENGAGEMENT_DECISION_STATUS = ("pending", "in_review", "approved", "superseded")
DETECTION_STATE = ("found", "checked_absent", "not_checked")


class Extractor(Base):
    """A step 3 extractor and the signals it declares it can emit (Part C
    'Extractor declarations'). A signal can be declared ahead of its
    extraction code without being unclaimed, two ways: on a `planned`
    extractor (a new extractor), or in an `implemented` extractor's
    `planned_emits` (an extractor that ships, gaining a signal). Either way
    the signal is `not_ready` / `extractor_not_implemented` until it is in
    `emits` of an `implemented` extractor."""

    __tablename__ = "extractors"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    emits: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    planned_emits: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    owner_team: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"status IN {EXTRACTOR_STATUS}", name="ck_extractors_status"),
    )


class SignalRegistryEntry(Base):
    """One registered step 3 signal. Rows come from the versioned
    signal-registry-*.json files step 3 ships, or are registered ahead of
    their extractor through the API. `state` and `state_reason` are computed
    (app/items/readiness.py), never written by a caller."""

    __tablename__ = "signal_registry_entries"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # The registry file's `extractor` field. Must be a registered extractor
    # listing this signal in `emits`; otherwise the signal is unclaimed,
    # which is a hard error.
    expected_extractor: Mapped[str] = mapped_column(Text, ForeignKey("extractors.name"), nullable=False)
    evidence_kind: Mapped[str] = mapped_column(Text, nullable=False)
    value_semantics: Mapped[str | None] = mapped_column(Text)
    # Compared against a fingerprint's signal_registry_version to tell
    # `not_checked` apart from `checked_absent` (Part G).
    signal_introduced_in_version: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="not_ready")
    state_reason: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"state IN {READINESS_STATE}", name="ck_signal_registry_entries_state"),
        CheckConstraint(f"category IN {SIGNAL_CATEGORY}", name="ck_signal_registry_entries_category"),
        CheckConstraint(f"type IN {SIGNAL_TYPE}", name="ck_signal_registry_entries_type"),
        CheckConstraint(
            f"evidence_kind IN {SIGNAL_EVIDENCE_KIND}", name="ck_signal_registry_entries_evidence_kind"
        ),
    )


class CatalogItem(Base):
    """A thing that needs work (Part D). Client-agnostic master catalog."""

    __tablename__ = "catalog_items"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    detection: Mapped[dict] = mapped_column(JSONB, nullable=False)
    excluded_roles: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    # Computed from signal readiness, never set directly (Part C).
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="not_ready")
    state_reason: Mapped[dict | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    owner_team: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(Text)
    # Hash of the content the seed last wrote (app/items/baseline.py): a
    # reseed never overwrites a row edited since. Null: no baseline.
    seeded_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"scope IN {ITEM_SCOPE}", name="ck_catalog_items_scope"),
        CheckConstraint(f"category IN {ITEM_CATEGORY}", name="ck_catalog_items_category"),
        CheckConstraint(f"state IN {READINESS_STATE}", name="ck_catalog_items_state"),
        CheckConstraint(f"status IN {ITEM_STATUS}", name="ck_catalog_items_status"),
        Index("ix_catalog_items_state", "state"),
    )


class ItemResolution(Base):
    """One option for resolving a catalog item, i.e. the menu (Part F).
    Client-agnostic; grows across engagements."""

    __tablename__ = "item_resolutions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    item_id: Mapped[str] = mapped_column(Text, ForeignKey("catalog_items.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    target_description: Mapped[str | None] = mapped_column(Text)
    consumer_impact: Mapped[str] = mapped_column(Text, nullable=False)
    effort: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    linux_compatible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    container_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(Text)
    # Hash of the content the seed last wrote (app/items/baseline.py): a
    # reseed never overwrites a row edited since. Null: no baseline.
    seeded_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"consumer_impact IN {CONSUMER_IMPACT}", name="ck_item_resolutions_consumer_impact"),
        CheckConstraint(f"effort IN {EFFORT}", name="ck_item_resolutions_effort"),
        CheckConstraint(f"status IN {ITEM_STATUS}", name="ck_item_resolutions_status"),
        UniqueConstraint("item_id", "name", name="uq_item_resolutions_item_id_name"),
        # At most one default per item. A soft-deleted default doesn't count.
        Index(
            "uq_item_resolutions_one_default",
            "item_id",
            unique=True,
            postgresql_where=text("is_default AND deleted_at IS NULL"),
        ),
        Index("ix_item_resolutions_item_id", "item_id"),
    )


DERIVATION_ACTIONS = ("derive", "not_derived", "subsume", "not_subsumed")
DERIVATION_APPLIES_TO = ("all", "internal_clients")


class ResolutionDerivation(Base):
    """What choosing one resolution of a leading item means for a dependent
    item (28-ITEM Part U). Master catalog data, authored beside the
    resolution in catalog_items.yaml: a new resolution declares its
    derivations as data, not code.

    - derive: the dependent's decision is derived as dependent_resolution_id
      (applies_to 'internal_clients': only on projects whose integration
      edges reach the leader's project).
    - not_derived: the leading decision does not settle the dependent; it
      stays awaiting_decision, and `reason` says why.
    - subsume: the dependent, on the leader's project, is no separate work.
    - not_subsumed: it stays separate work; `reason` says why.
    """

    __tablename__ = "resolution_derivations"

    resolution_id: Mapped[str] = mapped_column(Text, ForeignKey("item_resolutions.id"), primary_key=True)
    dependent_item_id: Mapped[str] = mapped_column(Text, ForeignKey("catalog_items.id"), primary_key=True)
    # The leading item: the resolution's own item, kept for keyed lookups.
    item_id: Mapped[str] = mapped_column(Text, ForeignKey("catalog_items.id"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    dependent_resolution_id: Mapped[str | None] = mapped_column(Text, ForeignKey("item_resolutions.id"))
    applies_to: Mapped[str] = mapped_column(Text, nullable=False, server_default="all")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(Text)
    # Hash of the content the seed last wrote (app/items/baseline.py): a
    # reseed never overwrites a row edited since. Null: no baseline.
    seeded_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"action IN {DERIVATION_ACTIONS}", name="ck_resolution_derivations_action"),
        CheckConstraint(f"applies_to IN {DERIVATION_APPLIES_TO}", name="ck_resolution_derivations_applies_to"),
        CheckConstraint("(action = 'derive') = (dependent_resolution_id IS NOT NULL)",
                        name="ck_resolution_derivations_derive_names_resolution"),
        CheckConstraint("dependent_item_id <> item_id", name="ck_resolution_derivations_not_self"),
        Index("ix_resolution_derivations_item_id", "item_id"),
        Index("ix_resolution_derivations_dependent_item_id", "dependent_item_id"),
    )


class EngagementDecision(Base):
    """An engagement's chosen resolution for one item (Part F). Engagement
    data: never written by, or into, the master catalog tables."""

    __tablename__ = "engagement_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    engagement_id: Mapped[str] = mapped_column(Text, ForeignKey("engagements.id"), nullable=False)
    item_id: Mapped[str] = mapped_column(Text, ForeignKey("catalog_items.id"), nullable=False)
    # Nullable: a pending decision may not have chosen yet. Approval requires it.
    resolution_id: Mapped[str | None] = mapped_column(Text, ForeignKey("item_resolutions.id"))
    # What was on the menu when the decision was taken. The menu grows
    # across engagements, so this is history; validation uses the full menu.
    candidates_considered: Mapped[list | None] = mapped_column(JSONB)
    rationale: Mapped[str | None] = mapped_column(Text)
    # A pair, per 25-STANDARDS-AND-VIEWPOINTS.md A1: the quality concern
    # that forced a higher-impact choice, and why.
    forcing_perspective: Mapped[str | None] = mapped_column(Text)
    forcing_rationale: Mapped[str | None] = mapped_column(Text)
    evaluation_notes: Mapped[str | None] = mapped_column(Text)
    approver_name: Mapped[str | None] = mapped_column(Text)
    approver_role: Mapped[str | None] = mapped_column(Text)
    decision_date: Mapped[datetime.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    # Part U: 'derived' — this decision follows another item's decision
    # (derived_from_decision_id) by the catalog's resolution_derivations row
    # for that decision's resolution (app/items/coupling.py). A derived
    # decision overridden by hand becomes 'manual', keeps the link, and sets
    # overrides_derivation.
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="manual")
    derived_from_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagement_decisions.id", ondelete="SET NULL", name="fk_engagement_decisions_derived_from")
    )
    # The leader's resolution this decision was derived from or, for an
    # override, overridden against. When the leader's decision no longer
    # matches it, an override is flagged needs_review (review_note names the
    # old and new leading decisions); any write to the decision clears it.
    derived_against_resolution_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("item_resolutions.id", ondelete="SET NULL", name="fk_engagement_decisions_derived_against")
    )
    overrides_derivation: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"status IN {ENGAGEMENT_DECISION_STATUS}", name="ck_engagement_decisions_status"),
        CheckConstraint("source IN ('manual', 'derived')", name="ck_engagement_decisions_source"),
        CheckConstraint(
            f"forcing_perspective IS NULL OR forcing_perspective IN {FORCING_PERSPECTIVE}",
            name="ck_engagement_decisions_forcing_perspective",
        ),
        Index(
            "uq_engagement_decisions_live",
            "engagement_id",
            "item_id",
            unique=True,
            postgresql_where=text("status <> 'superseded'"),
        ),
        Index("ix_engagement_decisions_engagement_id", "engagement_id"),
    )


class EngagementItemScope(Base):
    """The client-scoped overlay on a catalog item: `engagement_patterns`
    renamed (Part Q). Lazy: no row means active and not deleted."""

    __tablename__ = "engagement_item_scope"

    engagement_id: Mapped[str] = mapped_column(Text, ForeignKey("engagements.id"), primary_key=True)
    item_id: Mapped[str] = mapped_column(Text, ForeignKey("catalog_items.id"), primary_key=True)
    scope_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    deferred_reason: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"scope_status IN {SCOPE_STATUS}", name="ck_engagement_item_scope_scope_status"),
        Index("ix_engagement_item_scope_engagement_id", "engagement_id"),
    )


class ItemOccurrence(Base):
    """The work list's raw rows (Part G). Written by step 6 (item-detection),
    replaced per repository on rescan. `signal_registry_version` records what
    was true when detected, so a row survives its signal's extractor being
    removed later."""

    __tablename__ = "item_occurrences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(Text, ForeignKey("catalog_items.id"), nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text)
    # Set for a `group_by: source_path_and_value` item, where one file holds
    # several occurrences (one per connection string, one per secret key).
    value: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list | None] = mapped_column(JSONB)
    signal_registry_version: Mapped[str] = mapped_column(Text, nullable=False)
    detection_state: Mapped[str] = mapped_column(Text, nullable=False)
    # 'possible' when every piece of evidence is ambiguous (a call site an
    # unchanged overload could equally take): shown apart in the work list
    # and left out of work totals by default. Otherwise 'confirmed'.
    certainty: Mapped[str] = mapped_column(Text, nullable=False, server_default="confirmed")
    step_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    detected_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"scope IN {ITEM_SCOPE}", name="ck_item_occurrences_scope"),
        CheckConstraint("certainty IN ('confirmed', 'possible')", name="ck_item_occurrences_certainty"),
        CheckConstraint(f"detection_state IN {DETECTION_STATE}", name="ck_item_occurrences_detection_state"),
        # A location only ever sits on a found occurrence-scope row. Such a
        # row may still have none (found on a signal that locates nothing);
        # application scope, checked_absent and not_checked rows are per
        # project, file_path null.
        CheckConstraint(
            "file_path IS NULL OR (scope = 'occurrence' AND detection_state = 'found')",
            name="ck_item_occurrences_file_path",
        ),
        Index(
            "uq_item_occurrences_located",
            "project_id",
            "item_id",
            "file_path",
            "value",
            unique=True,
            postgresql_where=text("file_path IS NOT NULL"),
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "uq_item_occurrences_project",
            "project_id",
            "item_id",
            unique=True,
            postgresql_where=text("file_path IS NULL"),
        ),
        Index("ix_item_occurrences_repository_id", "repository_id"),
        Index("ix_item_occurrences_item_id", "item_id"),
    )


# Step 4, entry-point-inventory — 29-STEPS-004-005-INVENTORIES.md Part B1.
ENTRY_POINT_KIND = (
    "http_controller_action",
    "http_minimal_api",
    "wcf_operation",
    "asmx_web_method",
    "grpc_service_method",
    "signalr_hub_method",
    "message_consumer",
    "hosted_service",
    "scheduled_job",
    "console_main",
    "webforms_page",
    # entry-point-inventory 1.1.0.
    "razor_page",
    # 2.0.0.
    "windows_service",
    "http_handler",
    "global_asax",
    "owin_startup",
    "blazor_component",
    "azure_function",
    "desktop_app",
)
AUTH_DECLARED = ("declared", "none_declared", "not_assessed")
# 2.1.0: framework = a registered type no project in the repository declares;
# lifecycle = bootstrap and wiring, not a place external work enters.
ENTRY_POINT_ORIGIN = ("application", "framework")
ENTRY_CLASS = ("request", "lifecycle")


class EntryPoint(Base):
    """One row per entry point — what can call an application. Written by
    step 4 (entry-point-inventory), replaced per repository on rescan. See
    29-STEPS-004-005-INVENTORIES.md Part B4.

    `id` is derived, not random (sha256 over repository, project, kind,
    handler, route and verb, truncated), so it is stable across rescans and
    anything keyed to an entry point survives one. `detail` is the
    kind-specific block (`http`, `wcf`, `grpc`, ...), camelCase as in the
    artifact. `auth_declared` (declared | none_declared | not_assessed; null
    where it does not apply) is an addition to Part B4's column list, kept
    as a column so the per-project count is a query. It reports
    authentication declared in source and config only: gateway, proxy and
    header-based authentication are invisible to static analysis, so
    none_declared is a review prompt, not a security finding."""

    __tablename__ = "entry_points"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    handler_type: Mapped[str] = mapped_column(Text, nullable=False)
    handler_member: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    confidence_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    auth_declared: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default="application")
    entry_class: Mapped[str] = mapped_column(Text, nullable=False, server_default="request")
    step_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    detected_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"kind IN {ENTRY_POINT_KIND}", name="ck_entry_points_kind"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_entry_points_confidence"),
        CheckConstraint(f"auth_declared IS NULL OR auth_declared IN {AUTH_DECLARED}", name="ck_entry_points_auth_declared"),
        CheckConstraint(f"origin IN {ENTRY_POINT_ORIGIN}", name="ck_entry_points_origin"),
        CheckConstraint(f"entry_class IN {ENTRY_CLASS}", name="ck_entry_points_entry_class"),
        # Authentication is a question about requests.
        CheckConstraint("entry_class = 'request' OR auth_declared IS NULL", name="ck_entry_points_lifecycle_auth"),
        Index("ix_entry_points_project_id_kind", "project_id", "kind"),
        Index("ix_entry_points_repository_id_kind", "repository_id", "kind"),
    )


class EntryPointScan(Base):
    """1:1 with `repositories` — step 4's repository-level summary, as
    `fingerprint_scans` is step 3's. Carries what the rows alone cannot:
    per-project counts including skipped projects, the project-wide
    authorisation written in source, and the conventional route tables."""

    __tablename__ = "entry_point_scans"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    scanner_version: Mapped[str] = mapped_column(Text, nullable=False)
    skip_source: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    project_summaries: Mapped[list] = mapped_column(JSONB, nullable=False)
    # {manifestVersion, kinds}: what the scan looked for (2.0.0 onwards).
    capabilities: Mapped[dict | None] = mapped_column(JSONB)
    warnings: Mapped[list | None] = mapped_column(JSONB)
    step_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    scanned_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


# ---------- step 5: outbound-invocation inventory ----------

OUTBOUND_MECHANISM = (
    "http_client", "soap_client", "grpc_client", "database", "message_producer", "message_consumer",
    "cache", "secret_store", "file_share", "smtp", "ldap",
)
LINUX_VERDICT = ("incompatible", "requires_change", "unknown", "compatible")
ENDPOINT_RESOLUTION = ("resolved", "partial", "unresolved")
OUTBOUND_USAGE = ("used", "unused")


class OutboundInvocation(Base):
    """One row per outbound dependency of a project — what an application
    calls. Written by step 5 (outbound-invocation-inventory), replaced per
    repository on rescan. See 29-STEPS-004-005-INVENTORIES.md Part C8.

    `id` is derived (sha256 over repository, project, mechanism, normalised
    endpoint and contract, truncated), so it is stable across rescans. The
    endpoint columns hold the normalised endpoint only — userinfo, query and
    fragment are stripped before storage (Part C5). `detail` is
    {endpoint, block} with the mechanism's block (`soap`, `database`, ...)
    camelCase as in the artifact. `credentials` is kind and key path only,
    never a value. `endpoint_host` is what step 10's register aggregates on.

    `usage` is 'used' or 'unused'. An unused client (constructed nowhere,
    configured nowhere) makes no outbound call: the row is kept, but step
    10's register reads usage = 'used' only. Each environment binding in
    `environment_bindings` carries its own `linuxVerdict`; `linux_verdict`
    is the worst of them."""

    __tablename__ = "outbound_invocations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    mechanism: Mapped[str] = mapped_column(Text, nullable=False)
    usage: Mapped[str] = mapped_column(Text, nullable=False, server_default="used")
    endpoint_scheme: Mapped[str | None] = mapped_column(Text)
    endpoint_host: Mapped[str | None] = mapped_column(Text)
    endpoint_port: Mapped[int | None] = mapped_column(Integer)
    endpoint_path: Mapped[str | None] = mapped_column(Text)
    resolution: Mapped[str] = mapped_column(Text, nullable=False)
    placeholder: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False)
    environment_bindings: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    call_sites: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # 1.2.0: what each call site invokes — {operation, verb, path, member,
    # resolution, reason, callSite} as in the artifact.
    operations: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # 1.3.0: where the client is created, when that differs from call_sites
    # (now where it is invoked).
    construction_sites: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    credentials: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    auth_declared: Mapped[str | None] = mapped_column(Text)
    linux_verdict: Mapped[str] = mapped_column(Text, nullable=False)
    linux_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    confidence_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    step_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    detected_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"mechanism IN {OUTBOUND_MECHANISM}", name="ck_outbound_invocations_mechanism"),
        CheckConstraint(f"linux_verdict IN {LINUX_VERDICT}", name="ck_outbound_invocations_linux_verdict"),
        CheckConstraint(f"resolution IN {ENDPOINT_RESOLUTION}", name="ck_outbound_invocations_resolution"),
        CheckConstraint(f"auth_declared IS NULL OR auth_declared IN {AUTH_DECLARED}", name="ck_outbound_invocations_auth_declared"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_outbound_invocations_confidence"),
        CheckConstraint(f"usage IN {OUTBOUND_USAGE}", name="ck_outbound_invocations_usage"),
        Index("ix_outbound_invocations_repository_id_mechanism", "repository_id", "mechanism"),
        Index("ix_outbound_invocations_usage_endpoint_host", "usage", "endpoint_host"),
        Index("ix_outbound_invocations_endpoint_host", "endpoint_host"),
        Index("ix_outbound_invocations_linux_verdict", "linux_verdict"),
    )


class OutboundScan(Base):
    """1:1 with `repositories` — step 5's repository-level summary, as
    `entry_point_scans` is step 4's: per-project counts by mechanism and
    verdict, skipped projects included, and each project's incompatible list."""

    __tablename__ = "outbound_scans"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    scanner_version: Mapped[str] = mapped_column(Text, nullable=False)
    skip_source: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    project_summaries: Mapped[list] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list | None] = mapped_column(JSONB)
    step_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    scanned_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


# ---------- step 6: dependency assessment ----------

PACKAGE_OUTCOME = ("current", "upgrade_safe", "upgrade_breaking", "no_compatible_version", "unknown")


class PackageAssessment(Base):
    """One row per project per direct package — whether it can move to the
    engagement's target framework, to what, and which call sites break.
    Written by step 6 (dependency-assessment), replaced per repository on
    rescan. See 30-STEP-006-DEPENDENCY-ASSESSMENT.md Part F. `id` is derived
    (sha256 over repository, project and package id). `feed_url` is
    normalised: nothing derived from a feed credential is stored (Part B4)."""

    __tablename__ = "package_assessments"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    package_id: Mapped[str] = mapped_column(Text, nullable=False)
    current_version: Mapped[str | None] = mapped_column(Text)
    recommended_version: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    outcome_reason: Mapped[str | None] = mapped_column(Text)
    classification_method: Mapped[str | None] = mapped_column(Text)
    deprecated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    deprecation_replacement: Mapped[str | None] = mapped_column(Text)
    vulnerable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    vulnerability_max_severity: Mapped[str | None] = mapped_column(Text)
    vulnerabilities_resolved_by_upgrade: Mapped[bool | None] = mapped_column(Boolean)
    not_in_client_feed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    latest_public_version: Mapped[str | None] = mapped_column(Text)
    feed_source: Mapped[str | None] = mapped_column(Text)
    feed_name: Mapped[str | None] = mapped_column(Text)
    feed_url: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    breaking_members: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    call_sites: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    step_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    assessed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    # Artifact 1.1.0: what the package puts into the project, what a breaking
    # outcome rests on, the content-package risk flag and version drift.
    package_kind: Mapped[str | None] = mapped_column(Text)
    breaking_evidence: Mapped[str | None] = mapped_column(Text)
    content_breaking_possible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    version_drift: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        CheckConstraint(f"outcome IN {PACKAGE_OUTCOME}", name="ck_package_assessments_outcome"),
        CheckConstraint(
            "classification_method IS NULL OR classification_method IN ('api_diff', 'semver_heuristic', 'package_kind')",
            name="ck_package_assessments_method",
        ),
        CheckConstraint(
            "package_kind IS NULL OR package_kind IN ('runtime', 'build', 'tools', 'analyzer', 'content')",
            name="ck_package_assessments_kind",
        ),
        CheckConstraint(
            "breaking_evidence IS NULL OR breaking_evidence IN ('confirmed_call_sites', 'ambiguous_call_sites_only', 'semver_presumed')",
            name="ck_package_assessments_breaking_evidence",
        ),
        CheckConstraint(
            "feed_source IS NULL OR feed_source IN ('client_feed', 'nuget_org_fallback')",
            name="ck_package_assessments_feed_source",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_package_assessments_confidence"),
        Index("ix_package_assessments_repository_id_outcome", "repository_id", "outcome"),
        Index("ix_package_assessments_package_id", "package_id"),
    )


class PackageLookupCache(Base):
    """What one feed said about one package, and when (Part B6). Shared by
    every repository, reused within its TTL — not client data, and not
    cleared by the demo reset."""

    __tablename__ = "package_lookup_cache"

    feed_url_normalised: Mapped[str] = mapped_column(Text, primary_key=True)
    package_id: Mapped[str] = mapped_column(Text, primary_key=True)
    versions: Mapped[list] = mapped_column(JSONB, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------- Lifecycle step 11: estate dependency map (31-STEP-011-ESTATE-DEPENDENCY-MAP.md) ----------
#
# Engagement-scoped. Every table but endpoint_annotations is replaced by each
# run of step 11 for its engagement; endpoint_annotations is human data and a
# run never writes it.

CONVERSATION_STATUS = ("not_started", "in_progress", "agreed", "resolved", "not_required")
ENDPOINT_CLASSIFICATION = ("internal", "external")
DEPENDENCY_EDGE_KIND = ("project_reference", "internal_package")


class EstateSource(Base):
    """Lineage (Part B1): per repository, which step execution's rows step 11
    read, for each per-repository step it reads from."""

    __tablename__ = "estate_sources"

    engagement_id: Mapped[str] = mapped_column(Text, ForeignKey("engagements.id", ondelete="CASCADE"), primary_key=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    step_name: Mapped[str] = mapped_column(Text, primary_key=True)
    step_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    estate_step_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class EndpointRegisterHost(Base):
    """One row per host per engagement (Part C2). `host` is the register key:
    a normalised real host, or for a development address 'localhost@<repo>'
    (served by that repository) or 'localhost:<port>'. A host only annotations
    remember is kept with no_longer_called."""

    __tablename__ = "endpoint_register"

    engagement_id: Mapped[str] = mapped_column(Text, ForeignKey("engagements.id", ondelete="CASCADE"), primary_key=True)
    host: Mapped[str] = mapped_column(Text, primary_key=True)
    classification: Mapped[str] = mapped_column(Text, nullable=False)
    loopback: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    no_longer_called: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    calling_repository_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    calling_repositories: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    calling_project_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    calling_projects: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    mechanisms: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    bindings: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    ports: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    worst_verdict: Mapped[str | None] = mapped_column(Text)
    verdict_by_environment: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    requires_backend_change: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    backend_change_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    invocation_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # 'production_environment': keyed by the production environment's host,
    # other environments' hosts in other_hosts. 'host': no production binding,
    # keyed by the host as found.
    grouped_by: Mapped[str] = mapped_column(Text, nullable=False, server_default="host")
    other_hosts: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # Annotated hosts carried to this row when the production grouping moved
    # their calls here (C4). The annotation rows themselves are untouched.
    annotation_carried_from: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    step_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        CheckConstraint(f"classification IN {ENDPOINT_CLASSIFICATION}", name="ck_endpoint_register_classification"),
        CheckConstraint("grouped_by IN ('production_environment', 'host')", name="ck_endpoint_register_grouped_by"),
    )


class EndpointRegisterService(Base):
    """Path and contract groups beneath a host (C1), with the entry points
    that serve them when the host is internal (C3)."""

    __tablename__ = "endpoint_register_services"

    engagement_id: Mapped[str] = mapped_column(Text, ForeignKey("engagements.id", ondelete="CASCADE"), primary_key=True)
    host: Mapped[str] = mapped_column(Text, primary_key=True)
    path: Mapped[str] = mapped_column(Text, primary_key=True)
    contract: Mapped[str] = mapped_column(Text, primary_key=True, server_default="")
    ports: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    mechanisms: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    bindings: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    calling_repositories: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    calling_projects: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    worst_verdict: Mapped[str | None] = mapped_column(Text)
    requires_backend_change: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    internal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    internal_targets: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


class EndpointAnnotation(Base):
    """A human's record of the conversation about one host (C4). Keyed by
    the register's host, never an invocation id, and never written by a run:
    rescans regenerate invocations, this survives them."""

    __tablename__ = "endpoint_annotations"

    engagement_id: Mapped[str] = mapped_column(Text, ForeignKey("engagements.id", ondelete="CASCADE"), primary_key=True)
    host: Mapped[str] = mapped_column(Text, primary_key=True)
    owning_team: Mapped[str | None] = mapped_column(Text)
    contact: Mapped[str | None] = mapped_column(Text)
    conversation_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="not_started")
    target_date: Mapped[datetime.date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    # A human's statement that one of the estate's repositories serves this
    # host: HTTP calls to it are matched against that repository's routes.
    served_by_repository_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="SET NULL", name="fk_endpoint_annotations_served_by_repository")
    )
    updated_by: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"conversation_status IN {CONVERSATION_STATUS}", name="ck_endpoint_annotations_status"),
    )


class PackageEstateRow(Base):
    """One row per package per engagement (Part D)."""

    __tablename__ = "package_estate"

    engagement_id: Mapped[str] = mapped_column(Text, ForeignKey("engagements.id", ondelete="CASCADE"), primary_key=True)
    package_id: Mapped[str] = mapped_column(Text, primary_key=True)
    repository_count: Mapped[int] = mapped_column(Integer, nullable=False)
    repositories: Mapped[list] = mapped_column(JSONB, nullable=False)
    project_count: Mapped[int] = mapped_column(Integer, nullable=False)
    projects: Mapped[list] = mapped_column(JSONB, nullable=False)
    versions_in_use: Mapped[dict] = mapped_column(JSONB, nullable=False)
    estate_drift: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Versions differ between repositories, not only within one.
    cross_repository_drift: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    recommended_version: Mapped[str | None] = mapped_column(Text)
    outcomes: Mapped[dict] = mapped_column(JSONB, nullable=False)
    breaking_members: Mapped[list] = mapped_column(JSONB, nullable=False)
    flags: Mapped[dict] = mapped_column(JSONB, nullable=False)


class DependencyEdge(Base):
    """A project depending on another (E1)."""

    __tablename__ = "dependency_edges"

    engagement_id: Mapped[str] = mapped_column(Text, ForeignKey("engagements.id", ondelete="CASCADE"), primary_key=True)
    from_project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    to_project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    edge_kind: Mapped[str] = mapped_column(Text, primary_key=True)
    cross_repository: Mapped[bool] = mapped_column(Boolean, nullable=False)
    via_package: Mapped[str | None] = mapped_column(Text)
    client_feed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    __table_args__ = (CheckConstraint(f"edge_kind IN {DEPENDENCY_EDGE_KIND}", name="ck_dependency_edges_kind"),)


class SharedLibrary(Base):
    """A project depended on from two or more repositories (E2)."""

    __tablename__ = "shared_libraries"

    engagement_id: Mapped[str] = mapped_column(Text, ForeignKey("engagements.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    consumer_repository_count: Mapped[int] = mapped_column(Integer, nullable=False)
    consumer_project_count: Mapped[int] = mapped_column(Integer, nullable=False)
    consumers: Mapped[list] = mapped_column(JSONB, nullable=False)


class DependencyCycle(Base):
    """Projects that depend on each other (E3): wave planning treats a cycle
    as one unit."""

    __tablename__ = "dependency_cycles"

    engagement_id: Mapped[str] = mapped_column(Text, ForeignKey("engagements.id", ondelete="CASCADE"), primary_key=True)
    cycle_id: Mapped[str] = mapped_column(Text, primary_key=True)
    member_project_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    cross_repository: Mapped[bool] = mapped_column(Boolean, nullable=False)


class OriginReconciliation(Base):
    """Step 4's origin, corrected with the estate in view (E4). Step 4's own
    rows are never rewritten — its next rescan would revert them; consumers
    apply this overlay."""

    __tablename__ = "origin_reconciliations"

    engagement_id: Mapped[str] = mapped_column(Text, ForeignKey("engagements.id", ondelete="CASCADE"), primary_key=True)
    entry_point_id: Mapped[str] = mapped_column(Text, primary_key=True)
    original_origin: Mapped[str] = mapped_column(Text, nullable=False)
    reconciled_origin: Mapped[str] = mapped_column(Text, nullable=False)
    declaring_repository_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    declaring_project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class IntegrationEdge(Base):
    """One invoked operation of a call site matched to the entry point that
    serves it (31-STEP-011 Part I): SOAP by contract and operation, HTTP by
    verb and route template, gRPC by service and method. Same-repository
    edges are kept, flagged. Replaced per run."""

    __tablename__ = "integration_edges"

    engagement_id: Mapped[str] = mapped_column(Text, ForeignKey("engagements.id", ondelete="CASCADE"), primary_key=True)
    edge_id: Mapped[str] = mapped_column(Text, primary_key=True)
    mechanism: Mapped[str] = mapped_column(Text, nullable=False)
    caller_repository_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    caller_project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    invocation_id: Mapped[str] = mapped_column(Text, nullable=False)
    call_site_file: Mapped[str] = mapped_column(Text, nullable=False)
    call_site_line: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    callee_repository_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    callee_project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entry_point_id: Mapped[str] = mapped_column(Text, nullable=False)
    match_method: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    same_repository: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (Index("ix_integration_edges_entry_point", "engagement_id", "entry_point_id"),)


class IntegrationEntryPoint(Base):
    """Per matchable entry point: whether an internal caller was found. Never
    'unused' — an operation no estate code calls may be called from outside
    the estate."""

    __tablename__ = "integration_entry_points"

    engagement_id: Mapped[str] = mapped_column(Text, ForeignKey("engagements.id", ondelete="CASCADE"), primary_key=True)
    entry_point_id: Mapped[str] = mapped_column(Text, primary_key=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    matchable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    internal_caller: Mapped[str] = mapped_column(Text, nullable=False)
    caller_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cross_repository_caller_count: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("internal_caller IN ('internal_caller_found', 'no_internal_caller_found')",
                        name="ck_integration_entry_points_internal_caller"),
    )


class EntryPointBackend(Base):
    """Per step 4 entry point, the outbound call sites it reaches (step 5,
    1.3.0): status yes/no/unresolved, each call with its depth, the methods
    walked and whether it is conditional or in a loop, and the paths not
    followed (another class, an injected dependency, too deep). Written by
    step 5 and replaced per repository with its other rows."""

    __tablename__ = "entry_point_backend"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    entry_point_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    calls: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    unresolved: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    step_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (CheckConstraint("status IN ('yes', 'no', 'unresolved')", name="ck_entry_point_backend_status"),)
