"""The database is authoritative for the catalog — app/items/baseline.py.

A reseed never overwrites a catalog row edited since it was seeded: items,
resolutions and derivations. Hermetic: a fixture item and derivation,
written and edited through the same API handlers the UI calls, inside one
rolled-back transaction.

Run from backend/:  python -m unittest tests.test_catalog_baseline -v
"""

import copy
import unittest

from app import models
from app.items import baseline
from app.items import schemas as s
from app.routers import catalog_items
from app.seed.seed_data import upsert_authored_item
from tests.test_item_catalog import ItemCatalogTestCase
from tests.support import item_version

ITEM = {
    "id": "t-seeded", "name": "Seeded item", "scope": "application", "category": "hosting",
    "description": "Factory wording.",
    "detection": {"match": {"any": [{"id": "svc", "signal": {"name": "SVC_FILE"}}]}},
    "resolutions": [
        {"id": "t-seeded-a", "name": "Option A", "consumer_impact": "none", "effort": "low", "is_default": True},
        {"id": "t-seeded-b", "name": "Option B", "consumer_impact": "low", "effort": "low"},
    ],
}


class BaselineTests(ItemCatalogTestCase):
    def seed(self, data=None):
        report = baseline.new_report()
        registered = {row.name: row.evidence_kind for row in self.db.query(models.SignalRegistryEntry)}
        upsert_authored_item(self.db, copy.deepcopy(data or ITEM), registered, report)
        self.db.flush()
        return report

    def changed(self, **fields):
        data = copy.deepcopy(ITEM)
        data.update(fields)
        return data

    def item(self):
        return self.db.get(models.CatalogItem, "t-seeded")

    def edit_item_in_ui(self, **fields):
        item = self.item()
        payload = s.CatalogItemWrite(**{
            "name": item.name, "description": item.description, "scope": item.scope, "category": item.category,
            "detection": item.detection, "excluded_roles": item.excluded_roles, "owner_team": item.owner_team,
            "status": item.status, **fields})
        catalog_items.update_item("t-seeded", payload, db=self.db, if_match=item_version(self.db, "t-seeded"))

    def test_a_seeded_row_records_its_baseline(self):
        report = self.seed()
        self.assertEqual(report["inserted"], ["catalog_items t-seeded", "item_resolutions t-seeded-a", "item_resolutions t-seeded-b"])
        for row in (self.item(), self.db.get(models.ItemResolution, "t-seeded-a")):
            self.assertEqual(baseline.edit_state(row), "unedited")
        self.assertEqual(self.seed()["inserted"] + self.seed()["updated"], [])

    def test_an_unedited_row_follows_the_factory_default(self):
        self.seed()
        report = self.seed(self.changed(description="New factory wording."))
        self.assertEqual(report["updated"], ["catalog_items t-seeded"])
        self.assertEqual(self.item().description, "New factory wording.")
        self.assertEqual(baseline.edit_state(self.item()), "unedited")

    def test_a_ui_edit_is_never_overwritten(self):
        self.seed()
        self.edit_item_in_ui(description="The team's wording.")
        self.assertEqual(baseline.edit_state(self.item()), "edited")

        # The factory default did not change: the edit stands, quietly.
        report = self.seed()
        self.assertEqual((report["kept_edits"], report["conflicts"]), (["catalog_items t-seeded"], []))
        self.assertEqual(self.item().description, "The team's wording.")

        # Both changed: a conflict naming the row and both versions; the database row stands.
        report = self.seed(self.changed(description="New factory wording."))
        self.assertEqual(report["conflicts"], [{
            "table": "catalog_items", "row": "t-seeded", "reason": "edited since seeding, and the seed's default changed too",
            "fields": {"description": {"database": "The team's wording.", "seed": "New factory wording."}},
        }])
        self.assertEqual(self.item().description, "The team's wording.")

    def test_a_resolution_edit_is_never_overwritten(self):
        self.seed()
        resolution = self.db.get(models.ItemResolution, "t-seeded-b")
        catalog_items.update_resolution("t-seeded", "t-seeded-b", s.ResolutionWrite(
            name="Option B, as the team calls it", consumer_impact=resolution.consumer_impact, effort=resolution.effort), db=self.db,
            if_match=item_version(self.db, "t-seeded"))
        data = self.changed()
        data["resolutions"] = [ITEM["resolutions"][0], {**ITEM["resolutions"][1], "name": "Option B, renamed in the file"}]
        report = self.seed(data)
        self.assertEqual([(c["row"], c["fields"]["name"]) for c in report["conflicts"]],
                         [("t-seeded-b", {"database": "Option B, as the team calls it", "seed": "Option B, renamed in the file"})])
        self.assertEqual(self.db.get(models.ItemResolution, "t-seeded-b").name, "Option B, as the team calls it")

    def test_a_ui_soft_delete_is_never_undone(self):
        self.seed()
        catalog_items.delete_item("t-seeded", deleted_by="team", db=self.db)
        self.seed()
        self.assertIsNotNone(self.item().deleted_at)

    def test_a_row_without_a_baseline_is_adopted_only_when_it_equals_the_default(self):
        self.seed()
        self.item().seeded_hash = None
        self.assertEqual(self.seed()["adopted"], ["catalog_items t-seeded"])

        self.item().seeded_hash = None
        self.item().description = "Written before baselines existed."
        report = self.seed()
        self.assertEqual([c["reason"][:16] for c in report["conflicts"]], ["no seed baseline"])
        self.assertEqual(self.item().description, "Written before baselines existed.")
        self.assertIsNone(self.item().seeded_hash)

    def test_an_edited_derivation_is_never_overwritten_or_removed(self):
        self.seed()
        self.create_item("t-dependent", "application", {"match": {"any": [{"signal": {"name": "SVC_FILE"}}]}})
        key = {"resolution_id": "t-seeded-a", "dependent_item_id": "t-dependent"}
        default = {"item_id": "t-seeded", "action": "subsume", "dependent_resolution_id": None, "applies_to": "all",
                   "reason": "Factory reason.", "deleted": False}
        baseline.seed_row(self.db, models.ResolutionDerivation, key, default, baseline.new_report())
        self.db.flush()
        row = self.db.get(models.ResolutionDerivation, ("t-seeded-a", "t-dependent"))
        row.reason = "The team's reason."

        # No longer authored: an unedited row would be soft-deleted; this one is not.
        report = baseline.new_report()
        baseline.seed_row(self.db, models.ResolutionDerivation, key, {**default, "deleted": True}, report)
        self.assertEqual(report["conflicts"][0]["fields"], {
            "reason": {"database": "The team's reason.", "seed": "Factory reason."}, "deleted": {"database": False, "seed": True}})
        self.assertIsNone(row.deleted_at)

        row.reason = "Factory reason."   # back to the default: unedited again, so it follows the file
        baseline.seed_row(self.db, models.ResolutionDerivation, key, {**default, "deleted": True}, baseline.new_report())
        self.assertIsNotNone(row.deleted_at)


if __name__ == "__main__":
    unittest.main()
