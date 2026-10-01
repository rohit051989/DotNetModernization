import datetime
import uuid
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app import catalog_rules, models
from app.db import SessionLocal
from app.items import pattern_migration
from app.items import readiness as item_readiness
from app.items import registry as item_registry
from app.items.detection import validate_detection
from app.schemas import SignalRuleSet
from app.workflow import registration
from app.workflow.schemas import StepDeclaration

DATA_DIR = Path(__file__).parent / "data"

# A pattern added to the YAML without its own `rules` gets this inert empty
# rule set (rules_status defaults to 'draft', so it's never evaluated).
_EMPTY_SIGNAL_RULE_SET = SignalRuleSet.empty().model_dump(by_alias=True)


def _load(filename: str) -> dict:
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return yaml.safe_load(f)


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

    if "rules" in data:
        pattern.detection_rules = data["rules"]
    elif created:
        pattern.detection_rules = dict(_EMPTY_SIGNAL_RULE_SET)
    pattern.classification_role = data.get("classification_role", pattern.classification_role if not created else "PRIMARY")
    pattern.classification_family = data.get("classification_family")
    pattern.classification_value = data.get("classification_value")
    pattern.scope = data.get("scope", pattern.scope if not created else "PROJECT")
    pattern.priority = data.get("priority", pattern.priority if not created else 50)
    pattern.compatible_with = data.get("compatible_with", [])
    pattern.conflicts_with = data.get("conflicts_with", [])
    pattern.anchor_signals = data.get("anchor_signals", [])
    pattern.eligibility = data.get("eligibility")
    pattern.analysis_requirements = data.get("analysis_requirements")
    if "thresholds" in data:
        pattern.thresholds = data["thresholds"]
    elif created:
        pattern.thresholds = {"minimumScore": 70, "highConfidenceScore": 90}
    pattern.rules_status = data.get("rules_status", pattern.rules_status if not created else "draft")
    pattern.required_signals_pending = data.get("required_signals_pending", [])

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
    decision.forcing_perspective = data.get("forcing_perspective")
    decision.forcing_rationale = data.get("forcing_rationale")
    decision.rationale = data.get("rationale")
    decision.approver_name = data.get("approver_name")
    decision.approver_role = data.get("approver_role")
    decision_date = data.get("decision_date")
    decision.decision_date = datetime.date.fromisoformat(decision_date) if decision_date else None
    decision.status = data.get("status", "parked")
    return created


def seed() -> dict:
    """Idempotent upsert of the catalog seed data. Never deletes: resetting
    client and repository data is scripts/reset-demo.ps1's job alone
    (app/seed/reset_demo.py) — there is one reset path."""
    db = SessionLocal()
    try:
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
            created = _upsert_pattern(db, pattern_data)
            if created:
                counts["patterns_created"] += 1
            else:
                counts["patterns_updated"] += 1
            # Bulk seeding writes to `patterns` exactly like the API does, so it
            # must bump catalog_revision the same way (Part H) — otherwise a
            # reseed silently leaves classification runs pointing at a stale
            # revision number.
            catalog_rules.bump_catalog_revision(
                db, "pattern", pattern_data["id"], "insert" if created else "update"
            )
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
    """Registers all 35 lifecycle steps as stubs from lifecycle_steps.yaml —
    see 17-LIFECYCLE-STEPS.md v2.0. Idempotent upsert by step_name: re-run any time
    the file changes, no code changes needed.

    **Never downgrades an already-implemented step.** This used to rewrite
    every row unconditionally, which meant any `python -m app.seed` run — for
    a pattern edit, an engagement edit, anything — silently reset the four
    implemented steps to `adapter_type: stub`, `produces: []`,
    `implementation_status: stub`. The next discovery run then executed
    repository-ingest as a stub, it produced no `repository-inventory`
    artifact, and solution-discovery failed with "input
    'repository-inventory' did not resolve to an artifact" — a confusing
    error a long way from its cause.

    For an implemented row, only the descriptive fields this file actually
    owns are refreshed (display name, owner, viewpoint, lifecycle number);
    the adapter, contract and status are left alone, since those are owned by
    whoever implemented the step and registered it via
    `POST /api/workflow/steps`.

    **Never revives a retired step either.** A row that is soft-deleted
    (renamed) or deprecated (left the lifecycle) is skipped even if its
    step_name somehow reappears in the YAML — un-retiring a step is a
    deliberate act, not a side effect of a reseed. Retired rows absent from
    the YAML are never touched at all.
    """
    db = SessionLocal()
    try:
        steps_data = _load("lifecycle_steps.yaml")["steps"]
        created = 0
        updated = 0
        preserved = 0
        retired_skipped = 0
        for step_data in steps_data:
            existing = db.get(models.WfStepRegistration, step_data["step_name"])
            if existing is not None and (
                existing.deleted_at is not None or existing.implementation_status == "deprecated"
            ):
                retired_skipped += 1
                continue
            if existing is not None and existing.implementation_status != "stub":
                # Refresh only what lifecycle_steps.yaml is the source of
                # truth for. Adapter/contract/status/version stay as
                # registered.
                existing.lifecycle_step_no = step_data["lifecycle_step_no"]
                existing.display_name = step_data["display_name"]
                existing.owner_code = step_data["owner_code"]
                existing.viewpoint = step_data.get("viewpoint")
                preserved += 1
                continue

            declaration = StepDeclaration(
                step_name=step_data["step_name"],
                lifecycle_step_no=step_data["lifecycle_step_no"],
                display_name=step_data["display_name"],
                owner_code=step_data["owner_code"],
                viewpoint=step_data.get("viewpoint"),
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
            _row, was_created, _warnings, _invalidated = registration.register_step(db, declaration)
            if was_created:
                created += 1
            else:
                updated += 1
        db.commit()
        return {
            "steps_created": created,
            "steps_updated": updated,
            "steps_implemented_preserved": preserved,
            "steps_retired_skipped": retired_skipped,
            "steps_live": db.query(models.WfStepRegistration)
            .filter(
                models.WfStepRegistration.deleted_at.is_(None),
                models.WfStepRegistration.implementation_status != "deprecated",
            )
            .count(),
            "steps_total": db.query(models.WfStepRegistration).count(),
        }
    finally:
        db.close()


def seed_signal_registry() -> dict:
    """Loads extractors.yaml and mirrors the step 3 registry files into
    `extractors` / `signal_registry_entries`, then recomputes readiness —
    28-ITEM-AND-CONVERSION-MODEL.md Part C. Idempotent. Fails (and writes
    nothing) if any registered signal is unclaimed by its extractor's
    declaration."""
    db = SessionLocal()
    try:
        result = item_registry.sync_from_registry_files(
            db, _load("extractors.yaml")["extractors"], _load("anticipated_signals.yaml")["signals"]
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


_RESOLUTION_FIELDS = (
    "name", "description", "target_description", "consumer_impact", "effort",
    "is_default", "linux_compatible", "container_ready", "notes", "status",
)
_RESOLUTION_DEFAULTS = {"is_default": False, "linux_compatible": True, "container_ready": True, "status": "active"}


def seed_catalog_items() -> dict:
    """Upserts the authored items in catalog_items.yaml and their
    resolutions — 28-ITEM-AND-CONVERSION-MODEL.md Parts D to F. Same
    write-time validation as the API; readiness computed, never read from
    the file. `version` bumps only when detection or scope changes, so a
    reseed of an unchanged file is a no-op."""
    db = SessionLocal()
    try:
        registered = {row.name: row.evidence_kind for row in db.query(models.SignalRegistryEntry)}
        created = updated = 0
        states = {}
        for data in _load("catalog_items.yaml")["items"]:
            detection, _warnings = validate_detection(data["scope"], data["detection"], registered)
            item = db.get(models.CatalogItem, data["id"])
            if item is None:
                item = models.CatalogItem(id=data["id"], version=1)
                db.add(item)
                created += 1
            else:
                if item.detection != detection or item.scope != data["scope"]:
                    item.version += 1
                updated += 1
            item.name = data["name"]
            item.description = data.get("description")
            item.scope = data["scope"]
            item.category = data["category"]
            item.detection = detection
            item.excluded_roles = sorted(set(data.get("excluded_roles", [])))
            item.owner_team = data.get("owner_team")
            item.status = data.get("status", "active")
            db.flush()
            item_readiness.recompute_item(db, item)
            states[item.id] = item.state

            for res_data in data.get("resolutions", []):
                resolution = db.get(models.ItemResolution, res_data["id"])
                # Resolution ids are global primary keys. Reusing one under a
                # second item would silently re-point and overwrite the first
                # item's option, so it is a hard error.
                if resolution is not None and resolution.item_id != item.id:
                    raise ValueError(
                        f"Resolution id '{res_data['id']}' under item '{item.id}' already belongs to item "
                        f"'{resolution.item_id}'. Resolution ids are global: prefix it with the item id."
                    )
                if resolution is None:
                    resolution = models.ItemResolution(id=res_data["id"], item_id=item.id)
                    db.add(resolution)
                for field in _RESOLUTION_FIELDS:
                    setattr(resolution, field, res_data.get(field, _RESOLUTION_DEFAULTS.get(field)))
            db.flush()
        db.commit()
        return {"items_created": created, "items_updated": updated, "states": states}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def print_catalog_items_summary(result: dict) -> None:
    ready = sorted(k for k, v in result["states"].items() if v == "ready")
    print(
        f"Seeded: {len(result['states'])} authored catalog items "
        f"({result['items_created']} created, {result['items_updated']} updated); "
        f"{len(ready)} ready, {len(result['states']) - len(ready)} not_ready"
    )


def seed_pattern_migration() -> dict:
    """Part Q, idempotent: an item already migrated is left alone. See
    app/items/pattern_migration.py, which is also runnable (and revertible)
    on its own."""
    db = SessionLocal()
    try:
        report = pattern_migration.migrate(db)
        db.commit()
        return report
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def print_pattern_migration_summary(report: dict) -> None:
    print(
        f"Migrated patterns -> items: {len(report['items'])} new "
        f"({len(report['skipped_existing'])} already present, {len(report['amended'])} amended), "
        f"{report['resolutions']} resolutions, "
        f"{report['decisions']} decisions; {len(report['not_migrated_decisions'])} decision(s) left on "
        "non-migrated patterns"
    )


def print_signal_registry_summary(result: dict) -> None:
    print(
        f"Seeded: signal registry {result['registry_version']} "
        f"({result['signals_in_registry']} signals, {result['signals_anticipated']} anticipated, "
        f"{result['signals_created']} new) "
        f"from {result['extractors']} extractor declarations; "
        f"{len(result['signals_changed'])} signal and {len(result['items_changed'])} item state changes"
    )


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
        f"Seeded: {result['steps_live']} live lifecycle steps "
        f"({result['steps_created']} created, {result['steps_updated']} updated, "
        f"{result['steps_implemented_preserved']} implemented left untouched); "
        f"{result['steps_total'] - result['steps_live']} retired registrations kept for history"
    )
    if result["steps_retired_skipped"]:
        print(f"  WARNING: {result['steps_retired_skipped']} YAML entries name a retired step and were skipped")
