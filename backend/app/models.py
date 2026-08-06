import datetime
import uuid

from sqlalchemy import (
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

    __table_args__ = (
        CheckConstraint(
            f"status IN {LIFECYCLE_STATUS}", name="ck_patterns_status"
        ),
        Index("ix_patterns_status", "status"),
        Index("ix_patterns_category", "category"),
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
            postgresql_where=text("status <> 'superseded'"),
        ),
    )
