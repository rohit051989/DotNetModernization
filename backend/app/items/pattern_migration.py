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

Idempotent, and the database is authoritative (app/items/baseline.py):
the pattern tables and AMENDMENTS are the items' factory defaults. A
re-run inserts what is missing and brings a row not edited since it was
seeded to its default; it never overwrites a row edited since, and reports
a conflict where both changed. Readiness is computed, not copied — there is
no such thing on a pattern.

**Reversible.** `revert` removes exactly the rows this migration wrote,
identified by their source ids, and the derivations naming them. It refuses
if anything has been built on top of them since: occurrences detected for a
migrated item, resolutions or decisions on a migrated item that did not
come from the pattern tables, or any migrated item, resolution or
derivation edited since it was seeded (or with no baseline to prove it was
not) — it names each. Revert is the single place rows leave the item
tables, and only rows still exactly their factory default, which the seed
recreates — so it loses nothing.

    python -m app.items.pattern_migration             # migrate
    python -m app.items.pattern_migration --dry-run   # report, write nothing
    python -m app.items.pattern_migration --revert    # undo
"""

import argparse
import copy

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.db import SessionLocal
from app.errors import errors
from app.items import baseline, impact_rules, readiness
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
            # interactive-console-tool (registry 1.9.0) takes precedence: a
            # program that needs a person at the keyboard is not a batch job.
            {"id": "not-interactive-console-input", "signal": {"name": "INTERACTIVE_CONSOLE_INPUT"}},
        ],
        "resolutions": [
            {
                "id": "console-batch-job-not-deployable",
                "name": "Not a deployable workload — developer or test tool",
                "description": (
                    "The console application is a harness or tool a person runs by hand, not a workload: it is not "
                    "deployed. A console application that calls services and exits without keyboard input looks "
                    "identical to a batch job from its syntax, so this is the honest answer where detection cannot "
                    "tell them apart."
                ),
                "target_description": "Stays in the repository, run by hand outside OCP4",
                "consumer_impact": "none",
                "effort": "low",
                "is_default": False,
                "linux_compatible": True,
                "container_ready": True,
            },
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

# Impact rules (33-IMPACT-ANALYSIS Part D, K) for migrated resolutions, which have
# no YAML of their own to carry them: part of their factory default, seeded
# through the baseline like everything else. Keyed by resolution id.
_WEBFORMS_REWRITE = [
    {"id": "code-behind", "from": "seed", "select": "self", "filter": {"extension": ".cs"}, "action": "rewrite",
     "reason": "Page code-behind is rewritten as {target} — logic carried, the page lifecycle and ViewState are not"},
    # Markup that is itself the evidence (an .aspx found by its directives)
    # is replaced, not rewritten in place.
    {"id": "markup-evidence", "from": "seed", "select": "self", "filter": {"extension": [".aspx", ".ascx", ".master"]},
     "action": "delete", "reason": "Web Forms markup is replaced by {target}"},
    {"id": "markup", "from": "code-behind", "traverse": "convention_files", "kind": "webforms_markup", "action": "delete",
     "reason": "Web Forms markup (.aspx, .ascx, .master) does not run on ASP.NET Core; it is replaced by the new views"},
    {"id": "project", "from": "seed", "traverse": "project_file", "action": "rewrite",
     "reason": "The Web Application project becomes an SDK-style Microsoft.NET.Sdk.Web project"},
    {"id": "config", "from": "seed", "traverse": "config_elements", "path": "system.web", "action": "update",
     "reason": "system.web settings move to ASP.NET Core configuration and middleware"},
    {"id": "tests", "from": "code-behind", "traverse": "referencing_tests", "action": "update",
     "reason": "Tests of page code target the rewritten classes"},
]
RESOLUTION_IMPACT: dict[str, list] = {
    "aspnetcore-mvc-rewrite": [
        {**rule, "reason": rule["reason"].replace("{target}", "MVC controllers and Razor views")} for rule in _WEBFORMS_REWRITE
    ],
    "blazor-server-net10": [
        {**rule, "reason": rule["reason"].replace("{target}", "Blazor Server components")} for rule in _WEBFORMS_REWRITE
    ],
}

# Defaults for migrated items whose patterns recommended no option. Every
# active item has exactly one default (app/items/defaults.py); these two had
# none, and their options tie on consumer impact. Chosen in review:
# aspnet-webforms -> ASP.NET Core MVC rewrite, the conventional target for
# server-rendered pages; ssis-package -> SQL pushdown, lower effort at equal
# consumer impact. The pattern tables are not touched.
DEFAULT_AMENDMENTS: dict[str, str] = {
    "aspnet-webforms": "aspnetcore-mvc-rewrite",
    "ssis-package": "csharp-sql-pushdown",
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


def _amended_resolution_ids() -> set[str]:
    return {data["id"] for amendment in AMENDMENTS.values() for data in amendment.get("resolutions", [])}


def decision_from_record(record: models.DecisionRecord) -> models.EngagementDecision:
    """A pattern decision record as an item decision: same id (so it traces
    to its source), parked -> pending, the forcing perspective and rationale
    carried as the pair."""
    return models.EngagementDecision(
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


# ---------- migrate ----------


def migrated_item_content(pattern: models.Pattern, category: str, registered: dict[str, str]) -> dict:
    """A migrated item's factory default (app/items/baseline.py content):
    the pattern's detection with this module's AMENDMENTS and the
    architecture items' amendments (28-ITEM Part T); soft-deleted when an
    authored item replaces it (wcf-iis-servicemodel -> wcf-service)."""
    from app.items import architecture_items  # it imports the seeder, which imports this module

    detection = architecture_items.amend(pattern.id, item_detection(pattern.detection_rules, pattern.id))
    detection, _warnings = validate_detection("application", detection, registered)
    replaced_by = architecture_items.REPLACED_BY.get(pattern.id)
    return {
        "name": pattern.name, "description": item_description(pattern), "scope": "application", "category": category,
        "detection": detection, "excluded_roles": [], "owner_team": None,
        "status": "deprecated" if pattern.status == "deprecated" else "active",
        "deleted": replaced_by is not None,
        "_deleted_by": f"{architecture_items.APPLIED_BY}: replaced by {replaced_by}" if replaced_by else None,
    }


def migrated_resolution_contents(db: Session) -> list[tuple[str, dict]]:
    """(id, factory default) for every migrated resolution: the target state
    options of migrated patterns, then the AMENDMENTS resolutions."""
    contents = []
    for option in (
        db.query(models.TargetStateOption)
        .filter(models.TargetStateOption.pattern_id.in_(set(MIGRATED)))
        .order_by(models.TargetStateOption.pattern_id, models.TargetStateOption.id)
    ):
        contents.append((option.id, {
            "item_id": option.pattern_id, "name": option.name, "description": option.summary,
            "target_description": option.target_stack, "consumer_impact": option.consumer_impact, "effort": option.effort,
            "is_default": option.is_recommended or DEFAULT_AMENDMENTS.get(option.pattern_id) == option.id,
            "linux_compatible": option.linux_compatible,
            "container_ready": option.container_ready, "notes": _resolution_notes(option),
            "status": "deprecated" if option.status == "deprecated" else "active",
            "deleted": option.deleted_at is not None, "_deleted_at": option.deleted_at, "_deleted_by": option.deleted_by,
            "impact_rules": impact_rules.checked(RESOLUTION_IMPACT.get(option.id), f"resolution {option.id}"),
        }))
    for pattern_id in sorted(MIGRATED):
        for data in AMENDMENTS.get(pattern_id, {}).get("resolutions", []):
            contents.append((data["id"], {
                "item_id": pattern_id, "description": None, "target_description": None, "notes": None, "status": "active",
                "deleted": False, "impact_rules": impact_rules.checked(RESOLUTION_IMPACT.get(data["id"]), f"resolution {data['id']}"),
                **{k: v for k, v in data.items() if k != "id"},
            }))
    return contents


def migrate_catalog(db: Session, report: dict | None = None) -> tuple[dict, list[dict]]:
    """Migrated items and resolutions only (no engagement data), through the
    seed baseline: missing rows inserted, rows not edited since seeding
    brought to their factory default, edited rows left alone and reported
    (app/items/baseline.py). Returns (baseline report, inserted items)."""
    report = report if report is not None else baseline.new_report()
    registered = {row.name: row.evidence_kind for row in db.query(models.SignalRegistryEntry)}
    if not registered:
        raise RuntimeError("signal_registry_entries is empty: run `python -m app.seed` before migrating")

    inserted = []
    for pattern_id, category in MIGRATED.items():
        pattern = db.get(models.Pattern, pattern_id)
        if pattern is None or pattern.deleted_at is not None:
            raise RuntimeError(f"pattern '{pattern_id}' is missing or soft-deleted; the migration list is out of date")
        existing = db.get(models.CatalogItem, pattern_id)
        before = (existing.detection, existing.scope) if existing is not None else None
        # Same write-time validation as the API. Application scope, so this
        # also proves no occurrence_source slipped in.
        item, outcome = baseline.seed_row(db, models.CatalogItem, {"id": pattern_id},
                                          migrated_item_content(pattern, category, registered), report)
        if outcome == "updated" and before != (item.detection, item.scope):
            item.version += 1
        db.flush()
        readiness.recompute_item(db, item)
        if outcome == "inserted":
            inserted.append({"id": item.id, "state": item.state})

    for resolution_id, content in migrated_resolution_contents(db):
        baseline.seed_row(db, models.ItemResolution, {"id": resolution_id}, content, report)
    db.flush()
    return report, inserted


def migrate(db: Session) -> dict:
    catalog, inserted = migrate_catalog(db)
    return {"items": inserted, "baseline": catalog, **migrate_engagement_data(db)}


def migrate_engagement_data(db: Session) -> dict:
    """The engagement half: legacy decision records and pattern overlays onto
    the migrated items, whichever way those items arrived (this migration,
    or a catalog export imported at bootstrap). Never writes catalog rows."""
    report = {"decisions": 0, "scope_rows": 0, "not_migrated_decisions": []}
    migrated_ids = {item_id for item_id in MIGRATED if db.get(models.CatalogItem, item_id) is not None}

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
        db.add(decision_from_record(record))
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
    # Step 9's impact is built on those occurrences, and names the items' resolutions.
    impacts = db.query(models.ImpactSummary).filter(models.ImpactSummary.item_id.in_(item_ids)).count()
    if impacts:
        problems.append(f"{impacts} impact_summaries (step 9) reference migrated items")
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
    # The database is authoritative for the catalog (app/items/baseline.py):
    # revert removes only rows that are still exactly their factory default,
    # which the seed can recreate. A row edited since seeding — or with no
    # baseline to prove it was not — is team-authored data: revert refuses.
    resolution_ids = [r.id for r in db.query(models.ItemResolution.id).filter(models.ItemResolution.item_id.in_(item_ids))]
    derivations = db.query(models.ResolutionDerivation).filter(or_(
        models.ResolutionDerivation.item_id.in_(item_ids),
        models.ResolutionDerivation.dependent_item_id.in_(item_ids),
        models.ResolutionDerivation.dependent_resolution_id.in_(resolution_ids)))
    rows = (
        list(db.query(models.CatalogItem).filter(models.CatalogItem.id.in_(item_ids)).order_by(models.CatalogItem.id))
        + list(db.query(models.ItemResolution).filter(models.ItemResolution.item_id.in_(item_ids)).order_by(models.ItemResolution.id))
        + list(derivations.order_by(models.ResolutionDerivation.resolution_id, models.ResolutionDerivation.dependent_item_id))
    )
    for row in rows:
        state = baseline.edit_state(row)
        if state != "unedited":
            problems.append(f"{baseline.TABLES[type(row)]} {baseline.row_label(row)} "
                            + ("has been edited since it was seeded" if state == "edited" else "has no seed baseline to prove it unedited"))
    if problems:
        raise errors(
            409,
            [{"field": None, "message": f"Cannot revert: {p}.", "code": "REVERT_BLOCKED"} for p in problems],
        )

    # Derivations (28-ITEM Part U) naming a migrated item cannot outlive it.
    # Every one was proved unedited above — its factory default, which the
    # seed's derivation step recreates once the items are migrated again.
    counts = {
        "derivations": derivations.delete(synchronize_session=False),
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
    print(
        f"Migrated items and resolutions: {baseline.summary(report['baseline'])}; "
        f"{report['decisions']} decisions, {report['scope_rows']} engagement scope rows"
    )
    if report["baseline"]["conflicts"]:
        print(baseline.format_conflicts(report["baseline"]["conflicts"]))
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
