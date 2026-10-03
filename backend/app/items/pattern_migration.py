"""Part Q: move the pattern catalog into the item model, reversibly —
28-ITEM-AND-CONVERSION-MODEL.md Part Q.

Reads `patterns`, `target_state_options`, `decision_records` and
`engagement_patterns`; writes `catalog_items`, `item_resolutions`,
`engagement_decisions` and `engagement_item_scope`. **Never writes to the
source tables.** Both models run side by side until the new one is verified.

What moves (agreed in review, not re-derived here):

- The 8 work patterns and the 2 desktop patterns, all application scope with
  no occurrence_source (Part O scope test: at most once per project, and a
  choice about the project). Detection is the old `detection_rules` verbatim
  minus what fed the score: the `supporting` group, the `schema` tag, `none`
  conditions' `disqualify`/`penalty` flags (every existing `none` condition
  disqualifies, so none is lost), and `matchWarnings`, whose text moves into
  the item description — plus the explicit, reasoned AMENDMENTS below (today
  one: console-batch-job's precedence exclusions). Nothing else is added.
  `excluded_roles` stays empty so detection is equivalent to the old model
  for the side-by-side comparison, AMENDMENTS aside.
- Not migrated: the 6 role patterns (role is computed, Part D) and the 5
  already-modern patterns (they describe what an application is, not work).
  Decisions on those patterns stay where they are and are reported.
- target_state_options -> item_resolutions (same ids; is_recommended ->
  is_default, target_stack -> target_description).
- decision_records -> engagement_decisions (same ids, so each new row traces
  to its source; parked -> pending, other statuses unchanged; forcing
  perspective and rationale carried as the pair).
- engagement_patterns -> engagement_item_scope.

Idempotent: a row whose id already exists is left alone, so re-running
never overwrites an item edited after migration. Readiness is computed, not
copied — there is no such thing on a pattern.

**Reversible.** `revert` removes exactly the rows this migration wrote,
identified by their source ids. It refuses if anything has been built on top
of them since: occurrences detected for a migrated item, or resolutions or
decisions on a migrated item that did not come from the pattern tables.
Revert is the single place rows leave the item tables, and only rows that
are a copy of data still intact in the pattern tables — so it loses nothing.

    python -m app.items.pattern_migration             # migrate
    python -m app.items.pattern_migration --dry-run   # report, write nothing
    python -m app.items.pattern_migration --revert    # undo
"""

import argparse
import copy

from sqlalchemy.orm import Session

from app import models
from app.db import SessionLocal
from app.errors import errors
from app.items import readiness
from app.items.detection import validate_detection

# pattern id -> item category. All application scope.
MIGRATED = {
    # the 8 work patterns
    "aspnetcore-rest-api-legacy": "framework",
    "aspnet-webforms": "framework",
    "console-batch-job": "hosting",
    "fx47-class-library": "framework",
    "fx-aspnet-mvc": "framework",
    "ssis-package": "integration",
    "wcf-iis-servicemodel": "integration",
    "windows-service": "hosting",
    # the 2 desktop patterns, reframed as work: a desktop UI cannot land on OpenShift
    "winforms-desktop": "hosting",
    "wpf-desktop": "hosting",
}

NOT_MIGRATED = {
    "aspnetcore-minimal-api": "already modern: describes what the application is",
    "aspnetcore-mvc-modern": "already modern: describes what the application is",
    "blazor-server-modern": "already modern: describes what the application is",
    "blazor-webassembly-modern": "already modern: describes what the application is",
    "netstandard-modern-library": "already modern: describes what the application is",
    "role-application-project": "role pattern: role is computed in step 7 (Part D)",
    "role-database-project": "role pattern: role is computed in step 7 (Part D)",
    "role-deployment-project": "role pattern: role is computed in step 7 (Part D)",
    "role-library-project": "role pattern: role is computed in step 7 (Part D)",
    "role-test-project": "role pattern: role is computed in step 7 (Part D)",
    "role-unknown": "role pattern: role is computed in step 7 (Part D)",
}

# Decision 2 from review: WinForms keeps its old detection, with the gap stated.
_WINFORMS_NOTE = (
    "Detection note: `OutputType` WinExe covers both WinForms and WPF, so this item "
    "tells them apart only by the absence of XAML. Enhancement, not a blocker: positive "
    "WinForms signals (FORM_BASE_CLASS, SYSTEM_WINDOWS_FORMS_NAMESPACE, "
    "SYSTEM_WINDOWS_FORMS_ASSEMBLY, STA_THREAD_ATTRIBUTE) would let detection stop "
    "relying on an absence. Add them to `match` once step 3 emits them."
)

# Deliberate departures from the verbatim copy, each with its reason. These
# are the only places a migrated item differs from its pattern: extra `none`
# conditions (detection) or extra resolutions (the menu). The side-by-side
# comparison must allow for exactly these and nothing else. Applied on
# migrate, and also to an already-migrated item that lacks them (by id), so an
# existing database catches up. Amended resolutions count as migration-owned
# for revert.
AMENDMENTS: dict[str, dict] = {
    "console-batch-job": {
        "reason": (
            "Precedence (28-ITEM-AND-CONVERSION-MODEL.md Part E 'Overlapping items'): a hosted-service "
            "worker or a .NET Windows Service also has a Main method or top-level statements, so without "
            "these a worker matched console-batch-job as well as modern-worker-service or "
            "windows-service-hosting. The pattern's own exclusions only covered the .NET Framework "
            "ServiceBase shape."
        ),
        "none": [
            {"id": "not-background-service", "signal": {"name": "BACKGROUND_SERVICE_BASE_CLASS"}},
            {"id": "not-ihosted-service", "signal": {"name": "IHOSTED_SERVICE_BASE_CLASS"}},
            {"id": "not-add-hosted-service", "signal": {"name": "ADD_HOSTED_SERVICE_ENTRY_POINT"}},
            {"id": "not-use-windows-service", "signal": {"name": "USE_WINDOWS_SERVICE_INVOCATION"}},
            {"id": "not-windowsservices-package", "signal": {"name": "MICROSOFT_EXTENSIONS_HOSTING_WINDOWSSERVICES_PACKAGE"}},
        ],
    },
    "windows-service": {
        "reason": (
            "The pattern had one target state, below the catalog's two-option minimum. For the .NET "
            "Framework ServiceBase case, staying on Windows is a legitimate client answer, and choosing "
            "it on a Linux-targeted engagement must raise the decision warning."
        ),
        "resolutions": [
            {
                "id": "windows-service-remain-windows-hosted",
                "name": "Remain Windows-hosted (out of scope)",
                "description": "Out of scope for the Linux move; the service stays on Windows as a .NET Framework Windows Service.",
                "target_description": ".NET Framework on Windows Server, as a Windows Service",
                "consumer_impact": "none",
                "effort": "low",
                "is_default": False,
                "linux_compatible": False,
                "container_ready": False,
            },
        ],
    },
}

_DECISION_STATUS = {"parked": "pending", "in_review": "in_review", "approved": "approved", "superseded": "superseded"}


# ---------- transformation ----------


def item_detection(rules: dict, pattern_id: str | None = None) -> dict:
    """The old SignalRuleSet reduced to Part E `match`, plus that pattern's
    AMENDMENTS (if any). Nothing else added."""
    rules = copy.deepcopy(rules or {})
    match = {}
    for group in ("all", "any", "atLeast", "metadata"):
        if rules.get(group):
            match[group] = rules[group]
    if rules.get("none"):
        match["none"] = [
            {key: value for key, value in condition.items() if key not in ("disqualify", "penalty")}
            for condition in rules["none"]
        ]
    return apply_amendments(pattern_id, {"match": match})


def apply_amendments(pattern_id: str | None, detection: dict) -> dict:
    """Adds any amended `none` condition whose id the detection lacks.
    Returns the same dict. Leaves every other condition as it is, so an
    item edited after migration keeps its edits."""
    amendment = AMENDMENTS.get(pattern_id or "")
    if amendment and amendment.get("none"):
        none = detection["match"].setdefault("none", [])
        present = {condition.get("id") for condition in none}
        none.extend(copy.deepcopy(c) for c in amendment["none"] if c["id"] not in present)
    return detection


def item_description(pattern: models.Pattern) -> str:
    parts = [pattern.description or pattern.summary]
    for warning in (pattern.detection_rules or {}).get("matchWarnings", []):
        parts.append(f"Detection note (from the pattern's match warning): {warning}")
    if pattern.id == "winforms-desktop":
        parts.append(_WINFORMS_NOTE)
    return "\n\n".join(part.strip() for part in parts if part)


def _resolution_notes(option: models.TargetStateOption) -> str | None:
    parts = []
    if option.prerequisites:
        parts.append(f"Prerequisites: {option.prerequisites}")
    if option.known_limitations:
        parts.append(f"Known limitations: {option.known_limitations}")
    return "\n\n".join(parts) or None


def _missing_amended_resolutions(db: Session, pattern_id: str) -> list[dict]:
    """Amended resolutions for this item that are not in the table yet."""
    if db.get(models.CatalogItem, pattern_id) is None:
        return []
    return [
        data for data in AMENDMENTS.get(pattern_id, {}).get("resolutions", [])
        if db.get(models.ItemResolution, data["id"]) is None
    ]


def _amended_resolution_ids() -> set[str]:
    return {data["id"] for amendment in AMENDMENTS.values() for data in amendment.get("resolutions", [])}


# ---------- migrate ----------


def migrate(db: Session) -> dict:
    report = {
        "items": [], "resolutions": 0, "decisions": 0, "scope_rows": 0,
        "skipped_existing": [], "amended": [], "not_migrated_decisions": [],
    }
    registered = {row.name: row.evidence_kind for row in db.query(models.SignalRegistryEntry)}
    if not registered:
        raise RuntimeError("signal_registry_entries is empty: run `python -m app.seed` before migrating")

    for pattern_id, category in MIGRATED.items():
        pattern = db.get(models.Pattern, pattern_id)
        if pattern is None or pattern.deleted_at is not None:
            raise RuntimeError(f"pattern '{pattern_id}' is missing or soft-deleted; the migration list is out of date")
        existing = db.get(models.CatalogItem, pattern_id)
        if existing is not None:
            amended = apply_amendments(pattern_id, copy.deepcopy(existing.detection))
            if amended != existing.detection:
                existing.detection, _warnings = validate_detection(existing.scope, amended, registered)
                existing.version += 1
                db.flush()
                readiness.recompute_item(db, existing)
                report["amended"].append(pattern_id)
            elif not _missing_amended_resolutions(db, pattern_id):
                report["skipped_existing"].append(pattern_id)
            continue
        # Same write-time validation as the API. Application scope, so this
        # also proves no occurrence_source slipped in.
        detection, warnings = validate_detection("application", item_detection(pattern.detection_rules, pattern.id), registered)
        item = models.CatalogItem(
            id=pattern.id,
            name=pattern.name,
            description=item_description(pattern),
            scope="application",
            category=category,
            detection=detection,
            excluded_roles=[],
            version=1,
            status="deprecated" if pattern.status == "deprecated" else "active",
        )
        db.add(item)
        db.flush()
        readiness.recompute_item(db, item)
        report["items"].append({"id": item.id, "state": item.state, "warnings": warnings})

    db.flush()
    migrated_ids = set(MIGRATED)

    for option in (
        db.query(models.TargetStateOption)
        .filter(models.TargetStateOption.pattern_id.in_(migrated_ids))
        .order_by(models.TargetStateOption.pattern_id, models.TargetStateOption.id)
    ):
        if db.get(models.ItemResolution, option.id) is not None:
            continue
        db.add(
            models.ItemResolution(
                id=option.id,
                item_id=option.pattern_id,
                name=option.name,
                description=option.summary,
                target_description=option.target_stack,
                consumer_impact=option.consumer_impact,
                effort=option.effort,
                is_default=option.is_recommended,
                linux_compatible=option.linux_compatible,
                container_ready=option.container_ready,
                notes=_resolution_notes(option),
                status="deprecated" if option.status == "deprecated" else "active",
                deleted_at=option.deleted_at,
                deleted_by=option.deleted_by,
            )
        )
        report["resolutions"] += 1
    db.flush()

    for pattern_id in sorted(migrated_ids):
        missing = _missing_amended_resolutions(db, pattern_id)
        for data in missing:
            db.add(models.ItemResolution(item_id=pattern_id, **data))
            report["resolutions"] += 1
        if missing and pattern_id not in report["amended"]:
            report["amended"].append(pattern_id)
    db.flush()

    for record in db.query(models.DecisionRecord).filter(models.DecisionRecord.deleted_at.is_(None)).order_by(
        models.DecisionRecord.engagement_id, models.DecisionRecord.pattern_id
    ):
        if record.pattern_id not in migrated_ids:
            report["not_migrated_decisions"].append(
                {
                    "engagement_id": record.engagement_id,
                    "pattern_id": record.pattern_id,
                    "status": record.status,
                    "forcing_perspective": record.forcing_perspective,
                    "reason": NOT_MIGRATED.get(record.pattern_id, "pattern not in the migration list"),
                }
            )
            continue
        if db.get(models.EngagementDecision, record.id) is not None:
            continue
        db.add(
            models.EngagementDecision(
                id=record.id,
                engagement_id=record.engagement_id,
                item_id=record.pattern_id,
                resolution_id=record.selected_target_state_id,
                candidates_considered=record.candidates_considered,
                rationale=record.rationale,
                forcing_perspective=record.forcing_perspective,
                forcing_rationale=record.forcing_rationale,
                evaluation_notes=record.evaluation_notes,
                approver_name=record.approver_name,
                approver_role=record.approver_role,
                decision_date=record.decision_date,
                status=_DECISION_STATUS[record.status],
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )
        report["decisions"] += 1

    for overlay in db.query(models.EngagementPattern).filter(models.EngagementPattern.pattern_id.in_(migrated_ids)):
        if db.get(models.EngagementItemScope, (overlay.engagement_id, overlay.pattern_id)) is not None:
            continue
        db.add(
            models.EngagementItemScope(
                engagement_id=overlay.engagement_id,
                item_id=overlay.pattern_id,
                scope_status=overlay.scope_status,
                deferred_reason=overlay.deferred_reason,
                deleted_at=overlay.deleted_at,
                deleted_by=overlay.deleted_by,
            )
        )
        report["scope_rows"] += 1

    db.flush()
    return report


# ---------- revert ----------


def revert(db: Session) -> dict:
    item_ids = [i for i in MIGRATED if db.get(models.CatalogItem, i) is not None]
    option_ids = {
        row.id for row in db.query(models.TargetStateOption.id).filter(models.TargetStateOption.pattern_id.in_(MIGRATED))
    } | _amended_resolution_ids()
    record_ids = {row.id for row in db.query(models.DecisionRecord.id)}

    problems = []
    occurrences = db.query(models.ItemOccurrence).filter(models.ItemOccurrence.item_id.in_(item_ids)).count()
    if occurrences:
        problems.append(f"{occurrences} item_occurrences reference migrated items")
    foreign_resolutions = sorted(
        r.id
        for r in db.query(models.ItemResolution).filter(models.ItemResolution.item_id.in_(item_ids))
        if r.id not in option_ids
    )
    if foreign_resolutions:
        problems.append(f"resolutions added after migration: {', '.join(foreign_resolutions)}")
    foreign_decisions = [
        str(d.id)
        for d in db.query(models.EngagementDecision).filter(models.EngagementDecision.item_id.in_(item_ids))
        if d.id not in record_ids
    ]
    if foreign_decisions:
        problems.append(f"{len(foreign_decisions)} engagement decisions recorded after migration")
    if problems:
        raise errors(
            409,
            [{"field": None, "message": f"Cannot revert: {p}.", "code": "REVERT_BLOCKED"} for p in problems],
        )

    counts = {
        "decisions": db.query(models.EngagementDecision)
        .filter(models.EngagementDecision.item_id.in_(item_ids))
        .delete(synchronize_session=False),
        "scope_rows": db.query(models.EngagementItemScope)
        .filter(models.EngagementItemScope.item_id.in_(item_ids))
        .delete(synchronize_session=False),
        "resolutions": db.query(models.ItemResolution)
        .filter(models.ItemResolution.item_id.in_(item_ids))
        .delete(synchronize_session=False),
    }
    counts["items"] = (
        db.query(models.CatalogItem).filter(models.CatalogItem.id.in_(item_ids)).delete(synchronize_session=False)
    )
    db.flush()
    return counts


# ---------- CLI ----------


def _print_migrate(report: dict) -> None:
    for item in report["items"]:
        print(f"  item {item['id']:<28} {item['state']}")
        for warning in item["warnings"]:
            print(f"      warning: {warning}")
    if report["amended"]:
        print(f"  amended (AMENDMENTS): {', '.join(report['amended'])}")
    if report["skipped_existing"]:
        print(f"  already migrated, left alone: {', '.join(report['skipped_existing'])}")
    print(
        f"Migrated {len(report['items'])} items, {report['resolutions']} resolutions, "
        f"{report['decisions']} decisions, {report['scope_rows']} engagement scope rows"
    )
    for d in report["not_migrated_decisions"]:
        print(
            f"  NOT migrated: decision {d['engagement_id']} / {d['pattern_id']} ({d['status']}, "
            f"forcing_perspective={d['forcing_perspective']}) — {d['reason']}; still in decision_records"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Part Q: pattern catalog -> item catalog (reversible)")
    parser.add_argument("--revert", action="store_true", help="Remove exactly the rows a migrate wrote")
    parser.add_argument("--dry-run", action="store_true", help="Run and report, then roll back")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.revert:
            print(f"Reverted: {revert(db)}")
        else:
            _print_migrate(migrate(db))
        if args.dry_run:
            db.rollback()
            print("(dry run: rolled back)")
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
