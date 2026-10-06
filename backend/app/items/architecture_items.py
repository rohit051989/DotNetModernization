"""Architecture items on step 4's signals — 28-ITEM-AND-CONVERSION-MODEL.md
Part R (signal registry 1.8.0).

A WCF service is assembled across projects: contracts in one, the
implementation in another, the ServiceHost and system.serviceModel
configuration in a third, .svc files in a folder with no project file. The
migrated wcf-iis-servicemodel needed SERVICE_CONTRACT_ATTRIBUTE and an .svc
file or service-model configuration in one project, so on such a repository
it never fired and the most consequential decision was missing from the work
list. Step 4 has already put the service together; its architecture signals
(EXPOSES_WCF_SERVICE, HOSTS_WCF_SERVICE, ...) say what each project exposes
and hosts.

What this module holds. The database is authoritative for the catalog
(app/items/baseline.py): everything below is a factory default, applied by
the seed only to rows not edited since they were seeded.

- **Replacement — insert new, repoint, soft-delete.** wcf-service (authored,
  catalog_items.yaml) replaces wcf-iis-servicemodel. The old item's factory
  default is soft-deleted, naming its replacement (REPLACED_BY, applied by
  the pattern migration's item defaults; never hard-deleted). Once it is
  soft-deleted, `apply` repoints every decision on it to the new item —
  same id, so its history and its decision-record trace survive — with its
  resolution mapped to the new item's equivalent; engagement scope rows are
  copied. If the team has restored the old item, nothing is repointed.
- **Amendments — the audit.** Each migrated architecture item was checked for
  the same split-across-projects failure:
  - aspnet-webforms: an .aspx and its code-behind compile in one project, so
    no split; EXPOSES_WEBFORMS_UI is added as a further `any` rule (a page
    whose markup sits in an unfingerprinted folder still counts).
  - fx-aspnet-mvc: controllers in a class library, Global.asax in the web
    host, is a real split; step 3's controller signals still fire on the
    library, and EXPOSES_HTTP_API (step 4's resolved actions) is added.
  - asmx-service: code-behind in App_Code or a library is a real split;
    EXPOSES_ASMX_SERVICE is added. asmx-service is authored, so that rule
    is in catalog_items.yaml; AMENDMENTS holds only migrated items'.
  - aspnetcore-rest-api-legacy: Startup and the host builder live in the
    host project by construction; no split, unchanged.
  - console-batch-job: a service host is not a batch job — it fired on the
    WCF sample's Catalog.Host. Excluded on HOSTS_WCF_SERVICE and every
    EXPOSES_* signal.
  The amendments are part of each migrated item's factory default (`amend`,
  called by pattern_migration.migrated_item_content).
- **New items** wcf-service and wcf-service-host, and the resolutions
  migrate-to-service-protocol on wcf-nettcp-client and
  wcf-service-remain-windows-hosted on wcf-service, are seeded from
  catalog_items.yaml through the same baseline. What each wcf-service
  resolution derives is loaded separately, by app/items/derivations.py
  (Part U).

    python -m app.items.architecture_items             # apply
    python -m app.items.architecture_items --dry-run   # report, write nothing
"""

import argparse
import copy
import datetime

from sqlalchemy.orm import Session

from app import models
from app.db import SessionLocal
from app.items import baseline

APPLIED_BY = "architecture-items"

NEW_ITEMS = ("wcf-service", "wcf-service-host")
NEW_RESOLUTIONS = {
    "wcf-nettcp-client": ("migrate-to-service-protocol",),
    "wcf-service": ("wcf-service-remain-windows-hosted",),
}

REPLACEMENTS = [
    {
        "old": "wcf-iis-servicemodel",
        "new": "wcf-service",
        "resolutions": {
            "corewcf-net10": "wcf-service-corewcf",
            "rest-net10": "wcf-service-rest-rewrite",
            "grpc-net10": "wcf-service-grpc-rewrite",
        },
        "reason": "Detection required the contract and the hosting in one project; a WCF service assembled across "
                  "projects never matched. wcf-service detects on step 4's EXPOSES_WCF_SERVICE, whatever the hosting.",
    },
]

_EXPOSES = ("EXPOSES_WCF_SERVICE", "EXPOSES_HTTP_API", "EXPOSES_ASMX_SERVICE", "EXPOSES_GRPC_SERVICE", "EXPOSES_WEBFORMS_UI")

AMENDMENTS: dict[str, dict] = {
    "console-batch-job": {
        "none": [{"id": "not-wcf-host", "signal": {"name": "HOSTS_WCF_SERVICE"}}]
        + [{"id": "not-" + name.lower().replace("_", "-"), "signal": {"name": name}} for name in _EXPOSES],
    },
    "aspnet-webforms": {"any": [{"id": "exposes-webforms-ui", "signal": {"name": "EXPOSES_WEBFORMS_UI"}}]},
    "fx-aspnet-mvc": {"any": [{"id": "exposes-http-api", "signal": {"name": "EXPOSES_HTTP_API"}}]},
}

REPLACED_BY = {replacement["old"]: replacement["new"] for replacement in REPLACEMENTS}


def amend(item_id: str, detection: dict) -> dict:
    """Adds this module's amended conditions the detection lacks (by id).
    Pure: returns a new dict."""
    detection = copy.deepcopy(detection)
    for group, conditions in AMENDMENTS.get(item_id, {}).items():
        existing = detection["match"].setdefault(group, [])
        present = {c.get("id") for c in existing}
        existing.extend(copy.deepcopy(c) for c in conditions if c["id"] not in present)
    return detection


# Audited, no change: why, for the record.
UNCHANGED = {
    "aspnetcore-rest-api-legacy": "Startup class and WebHost/Host builder live in the host project by construction: no split.",
}


def apply(db: Session, dry_run: bool = False) -> dict:
    """Seeds the new authored items (through the baseline: an edited row is
    never overwritten) and repoints decisions off replaced items. Flushes;
    the caller commits (or, for a dry run, rolls back)."""
    from app.seed.seed_data import authored_item, upsert_authored_item  # the seeder imports this module

    report = {"baseline": baseline.new_report(), "repointed_decisions": [], "moved_scope_rows": 0, "unchanged": UNCHANGED}
    registered = {row.name: row.evidence_kind for row in db.query(models.SignalRegistryEntry)}
    for item_id in sorted(set(NEW_ITEMS) | set(NEW_RESOLUTIONS)):
        upsert_authored_item(db, authored_item(item_id), registered, report["baseline"])

    now = datetime.datetime.now(datetime.timezone.utc)
    for replacement in REPLACEMENTS:
        replace_item(db, replacement, report, now)

    db.flush()
    return report


def replace_item(db: Session, replacement: dict, report: dict, now: datetime.datetime) -> None:
    """Repoint: every decision on the replaced item moves to the new one with
    the same id, its resolution mapped; scope rows are copied. Only once the
    old item is soft-deleted (its factory default) — a replaced item the
    team has restored keeps its decisions. Idempotent: nothing is left to
    move on a second run."""
    old = db.get(models.CatalogItem, replacement["old"])
    new = db.get(models.CatalogItem, replacement["new"])
    if old is None or new is None or old.deleted_at is None:
        return
    for decision in db.query(models.EngagementDecision).filter(models.EngagementDecision.item_id == old.id):
        live_on_new = (
            db.query(models.EngagementDecision)
            .filter(models.EngagementDecision.engagement_id == decision.engagement_id,
                    models.EngagementDecision.item_id == new.id, models.EngagementDecision.status != "superseded")
            .first()
        )
        if live_on_new is not None and decision.status != "superseded":
            decision.status = "superseded"   # one live decision per item: the new item's own wins
        decision.item_id = new.id
        if decision.resolution_id is not None:
            decision.resolution_id = replacement["resolutions"].get(decision.resolution_id, decision.resolution_id)
        if decision.candidates_considered:
            decision.candidates_considered = [replacement["resolutions"].get(c, c) for c in decision.candidates_considered]
        note = f"Moved from {old.id} to {new.id} ({APPLIED_BY}): {replacement['reason']}"
        decision.evaluation_notes = note if not decision.evaluation_notes else f"{decision.evaluation_notes}\n\n{note}"
        decision.updated_at = now
        report["repointed_decisions"].append(str(decision.id))
    for row in db.query(models.EngagementItemScope).filter(models.EngagementItemScope.item_id == old.id):
        if db.get(models.EngagementItemScope, (row.engagement_id, new.id)) is None:
            db.add(models.EngagementItemScope(**{
                c.name: getattr(row, c.name) for c in models.EngagementItemScope.__table__.columns if c.name != "item_id"
            }, item_id=new.id))
            report["moved_scope_rows"] += 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the architecture-item changes (idempotent).")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change and write nothing.")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        report = apply(db, dry_run=args.dry_run)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
        print(("Would apply: " if args.dry_run else "Applied: ") + str(report))
    finally:
        db.close()


if __name__ == "__main__":
    main()
