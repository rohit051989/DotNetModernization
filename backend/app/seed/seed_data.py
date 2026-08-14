import datetime
import uuid
from pathlib import Path

import yaml
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.db import SessionLocal
from app.workflow import registration
from app.workflow.schemas import StepDeclaration

DATA_DIR = Path(__file__).parent / "data"


def _load(filename: str) -> dict:
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return yaml.safe_load(f)


def reset_tables(db: Session) -> None:
    db.execute(
        text(
            "TRUNCATE engagement_patterns, decision_records, target_state_options, "
            "engagements, patterns CASCADE"
        )
    )
    db.commit()


def _upsert_pattern(db: Session, data: dict) -> bool:
    """Upserts by id. Returns True if a new row was created."""
    pattern = db.get(models.Pattern, data["id"])
    created = pattern is None
    if pattern is None:
        pattern = models.Pattern(id=data["id"])
        db.add(pattern)

    pattern.name = data["name"]
    pattern.summary = data["summary"]
    pattern.description = data.get("description")
    pattern.legacy_stack = data["legacy_stack"]
    pattern.category = data["category"]
    pattern.detection_rules = data["detection_rules"]
    pattern.typical_indicators = data.get("typical_indicators")
    pattern.known_risks = data.get("known_risks")
    pattern.status = data.get("status", "active")
    return created


def _upsert_target_state(db: Session, pattern_id: str, data: dict) -> bool:
    """Upserts by id. Returns True if a new row was created."""
    option = db.get(models.TargetStateOption, data["id"])
    created = option is None
    if option is None:
        option = models.TargetStateOption(id=data["id"], pattern_id=pattern_id)
        db.add(option)

    option.pattern_id = pattern_id
    option.name = data["name"]
    option.summary = data["summary"]
    option.target_stack = data["target_stack"]
    option.consumer_impact = data["consumer_impact"]
    option.effort = data["effort"]
    option.linux_compatible = data.get("linux_compatible", True)
    option.container_ready = data.get("container_ready", True)
    option.is_lift_and_shift = data.get("is_lift_and_shift", False)
    option.is_recommended = data.get("is_recommended", False)
    option.engine_support = data.get("engine_support")
    option.playbook_md = data.get("playbook_md")
    option.prerequisites = data.get("prerequisites")
    option.known_limitations = data.get("known_limitations")
    option.status = data.get("status", "active")
    return created


def _upsert_engagement(db: Session, data: dict) -> bool:
    """Upserts by id. Returns True if a new row was created."""
    engagement = db.get(models.Engagement, data["id"])
    created = engagement is None
    if engagement is None:
        engagement = models.Engagement(id=data["id"])
        db.add(engagement)

    engagement.client_name = data["client_name"]
    engagement.description = data.get("description")
    engagement.target_platform = data.get("target_platform")
    engagement.default_posture = data.get("default_posture", "lift-and-shift")
    engagement.status = data.get("status", "active")
    return created


def _upsert_decision(db: Session, data: dict) -> bool:
    """Decision records have a generated UUID id, not a natural key from the seed
    data, so idempotency keys off the same (engagement_id, pattern_id) constraint
    the database itself enforces for live decisions. Returns True if created."""
    existing = (
        db.query(models.DecisionRecord)
        .filter(
            models.DecisionRecord.engagement_id == data["engagement_id"],
            models.DecisionRecord.pattern_id == data["pattern_id"],
            models.DecisionRecord.status != "superseded",
        )
        .first()
    )
    created = existing is None
    decision = existing or models.DecisionRecord(
        id=uuid.uuid4(),
        engagement_id=data["engagement_id"],
        pattern_id=data["pattern_id"],
    )
    if created:
        db.add(decision)

    decision.selected_target_state_id = data.get("selected_target_state_id")
    decision.candidates_considered = data.get("candidates_considered")
    decision.evaluation_notes = data.get("evaluation_notes")
    decision.forcing_factor = data.get("forcing_factor")
    decision.rationale = data.get("rationale")
    decision.approver_name = data.get("approver_name")
    decision.approver_role = data.get("approver_role")
    decision_date = data.get("decision_date")
    decision.decision_date = datetime.date.fromisoformat(decision_date) if decision_date else None
    decision.status = data.get("status", "parked")
    return created


def seed(reset: bool = False) -> dict:
    db = SessionLocal()
    try:
        if reset:
            reset_tables(db)

        counts = {
            "patterns_created": 0,
            "patterns_updated": 0,
            "target_state_options_created": 0,
            "target_state_options_updated": 0,
            "engagements_created": 0,
            "engagements_updated": 0,
            "decision_records_created": 0,
            "decision_records_updated": 0,
        }

        # Flushed in stages (rather than one flush at the end) because SQLAlchemy's
        # unit-of-work only orders inserts by FK dependency between mappers linked
        # via relationship() — these models use plain FK columns, so without staged
        # flushes decision_records can be inserted before the engagements/patterns/
        # target_state_options rows they reference exist.
        patterns_data = _load("patterns.yaml")["patterns"]
        for pattern_data in patterns_data:
            target_states_data = pattern_data.get("target_states", [])
            if _upsert_pattern(db, pattern_data):
                counts["patterns_created"] += 1
            else:
                counts["patterns_updated"] += 1
            db.flush()
            for ts_data in target_states_data:
                if _upsert_target_state(db, pattern_data["id"], ts_data):
                    counts["target_state_options_created"] += 1
                else:
                    counts["target_state_options_updated"] += 1
        db.flush()

        engagements_data = _load("engagements.yaml")["engagements"]
        for engagement_data in engagements_data:
            if _upsert_engagement(db, engagement_data):
                counts["engagements_created"] += 1
            else:
                counts["engagements_updated"] += 1
        db.flush()

        decisions_data = _load("decision_records.yaml")["decision_records"]
        for decision_data in decisions_data:
            if _upsert_decision(db, decision_data):
                counts["decision_records_created"] += 1
            else:
                counts["decision_records_updated"] += 1

        db.commit()

        coverage_by_engagement = {}
        for engagement_data in engagements_data:
            engagement_id = engagement_data["id"]
            live_decisions = (
                db.query(models.DecisionRecord)
                .filter(
                    models.DecisionRecord.engagement_id == engagement_id,
                    models.DecisionRecord.status != "superseded",
                )
                .all()
            )
            coverage_by_engagement[engagement_id] = {
                "approved": sum(1 for d in live_decisions if d.status == "approved"),
                "in_review": sum(1 for d in live_decisions if d.status == "in_review"),
                "parked": sum(1 for d in live_decisions if d.status == "parked"),
            }

        return {
            "counts": counts,
            "totals": {
                "patterns": db.query(models.Pattern).count(),
                "target_state_options": db.query(models.TargetStateOption).count(),
                "engagements": db.query(models.Engagement).count(),
                "decision_records": db.query(models.DecisionRecord).count(),
            },
            "coverage_by_engagement": coverage_by_engagement,
        }
    finally:
        db.close()


def seed_lifecycle_steps() -> dict:
    """Registers all 51 lifecycle steps as stubs from lifecycle_steps.yaml —
    see 17-LIFECYCLE-STEPS.md. Idempotent upsert by step_name: re-run any time
    the file changes, no code changes needed."""
    db = SessionLocal()
    try:
        steps_data = _load("lifecycle_steps.yaml")["steps"]
        created = 0
        updated = 0
        for step_data in steps_data:
            declaration = StepDeclaration(
                step_name=step_data["step_name"],
                lifecycle_step_no=step_data["lifecycle_step_no"],
                display_name=step_data["display_name"],
                owner_code=step_data["owner_code"],
                version="0.0.0",
                implementation_status="stub",
                consumes=[],
                produces=[],
                adapter_type="stub",
                adapter_config={
                    "exit_status": "NOT_IMPLEMENTED",
                    "message": "Awaiting implementation by platform team",
                },
            )
            _row, was_created, _warnings = registration.register_step(db, declaration)
            if was_created:
                created += 1
            else:
                updated += 1
        db.commit()
        return {
            "steps_created": created,
            "steps_updated": updated,
            "steps_total": db.query(models.WfStepRegistration).count(),
        }
    finally:
        db.close()


def print_summary(result: dict) -> None:
    totals = result["totals"]
    print(
        f"Seeded: {totals['patterns']} patterns, "
        f"{totals['target_state_options']} target state options, "
        f"{totals['engagements']} engagements, "
        f"{totals['decision_records']} decision records"
    )
    for engagement_id, coverage in result["coverage_by_engagement"].items():
        parts = [f"{key}: {value}" for key, value in coverage.items() if value > 0]
        if parts:
            print(f"  {engagement_id:<22} " + "   ".join(parts))


def print_steps_summary(result: dict) -> None:
    print(
        f"Seeded: {result['steps_total']} lifecycle steps "
        f"({result['steps_created']} created, {result['steps_updated']} updated)"
    )
