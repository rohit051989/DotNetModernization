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
STEP_OWNER_CODE = ("P", "C", "S", "H")
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
CLONE_URL_VERIFICATION = ("verified", "mismatch", "unverifiable")
SOURCE_TYPE = ("local_path", "git_clone")
CRITICALITY = ("low", "medium", "high", "critical")
RETIREMENT_STATUS = ("active", "slated_for_retirement", "decommissioned")
INGEST_STATUS = ("registered", "scanned", "scan_failed", "path_missing")


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
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    validation_status: Mapped[str] = mapped_column(Text, nullable=False)
    validation_errors: Mapped[dict | None] = mapped_column(JSONB)
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
    read_count: Mapped[int] = mapped_column(Integer, server_default="0")
    write_count: Mapped[int] = mapped_column(Integer, server_default="0")
    skip_count: Mapped[int] = mapped_column(Integer, server_default="0")
    commit_count: Mapped[int] = mapped_column(Integer, server_default="0")
    execution_context: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    stdout_tail: Mapped[str | None] = mapped_column(Text)
    stderr_tail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"batch_status IN {BATCH_STATUS}", name="ck_wf_step_executions_batch_status"),
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
