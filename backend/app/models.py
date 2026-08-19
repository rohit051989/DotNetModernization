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

ADAPTER_TYPE = ("python", "process", "http", "event", "stub")
# Combined codes (e.g. "P + S") denote shared authorship within one step and are
# stored verbatim — see 17-LIFECYCLE-STEPS.md "Owner codes".
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
# 22-STEP-SEQUENCING-AND-POLICY.md Part D. Null unless exit_status is SKIPPED
# (enforced by ck_wf_step_executions_skip_reason_pairing below).
SKIP_REASON = (
    "POLICY_DISABLED",
    "CONDITION_FALSE",
    "TIER_NOT_APPLICABLE",
    "UPSTREAM_SKIPPED",
    "CASCADED_POLICY",
)
CLONE_URL_VERIFICATION = ("verified", "mismatch", "unverifiable")
SOURCE_TYPE = ("local_path", "git_clone")
CRITICALITY = ("low", "medium", "high", "critical")
RETIREMENT_STATUS = ("active", "slated_for_retirement", "decommissioned")
INGEST_STATUS = ("registered", "scanned", "scan_failed", "path_missing")
SOURCE_STATUS = ("active", "archived", "disabled", "inaccessible")

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
        Index("ix_patterns_status", "status"),
        Index("ix_patterns_category", "category"),
        Index("ix_patterns_not_deleted", "id", postgresql_where=text("deleted_at IS NULL")),
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


class Engagement(Base):
    __tablename__ = "engagements"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    client_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    target_platform: Mapped[str | None] = mapped_column(Text)
    default_posture: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="lift-and-shift"
    )
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
    forcing_factor: Mapped[str | None] = mapped_column(Text)
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


class EngagementStepPolicy(Base):
    """A client's explicit override disabling one lifecycle step — see
    22-STEP-SEQUENCING-AND-POLICY.md Part C. Absence of a row means enabled;
    this table only ever holds deviations from default, so a newly
    registered step needs no backfill."""

    __tablename__ = "engagement_step_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    engagement_id: Mapped[str] = mapped_column(Text, ForeignKey("engagements.id"), nullable=False)
    step_name: Mapped[str] = mapped_column(
        Text, ForeignKey("wf_step_registrations.step_name"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # Mandatory when enabled is false (app-layer validation); nullable at the
    # DB level so a row explicitly re-recording "enabled" needs no reason.
    # A cascade-created row's reason is always the literal
    # "cascaded from disabling <step_name>" — the runtime distinguishes
    # skip_reason CASCADED_POLICY from POLICY_DISABLED by that convention
    # rather than a separate column (22-STEP-SEQUENCING-AND-POLICY.md Part C
    # documents no such column).
    reason: Mapped[str | None] = mapped_column(Text)
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
        UniqueConstraint("engagement_id", "step_name", name="uq_engagement_step_policies_engagement_step"),
        CheckConstraint("enabled OR reason IS NOT NULL", name="ck_engagement_step_policies_reason_required"),
        Index("ix_engagement_step_policies_engagement_id", "engagement_id"),
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
    registered_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"owner_code IN {STEP_OWNER_CODE}", name="ck_wf_step_registrations_owner_code"),
        CheckConstraint(f"adapter_type IN {ADAPTER_TYPE}", name="ck_wf_step_registrations_adapter_type"),
        CheckConstraint(
            f"implementation_status IN {IMPLEMENTATION_STATUS}",
            name="ck_wf_step_registrations_implementation_status",
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
    clone_url: Mapped[str] = mapped_column(Text, nullable=False)
    clone_url_normalised: Mapped[str] = mapped_column(Text, nullable=False)
    detected_clone_url: Mapped[str | None] = mapped_column(Text)
    clone_url_verification: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="unverifiable"
    )
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
            postgresql_where=text("deleted_at IS NULL"),
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
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    evidence: Mapped[list | None] = mapped_column(JSONB)
    extractor: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)

    __table_args__ = (
        CheckConstraint(f"signal_category IN {SIGNAL_CATEGORY}", name="ck_fingerprint_signals_category"),
        CheckConstraint(f"signal_type IN {SIGNAL_TYPE}", name="ck_fingerprint_signals_type"),
        CheckConstraint(f"source_type IN {EVIDENCE_SOURCE_TYPE}", name="ck_fingerprint_signals_source_type"),
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
