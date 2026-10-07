"""Item catalog export — app/items/catalog_export.py, 28-ITEM Part W.

Hermetic: fixture items written through the API handlers, inside one
rolled-back transaction. The fresh-database round trip is
`python -m app.items.catalog_export roundtrip` (it creates and drops a
database, which a rolled-back test transaction cannot).

Run from backend/:  python -m unittest tests.test_catalog_export -v
"""

import copy
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi import Response
from sqlalchemy import text

from app import models
from app.items import catalog_export
from app.items import schemas as s
from app.routers import catalog_items, item_decisions
from tests.support import TEST_ENGAGEMENT_ID
from tests.test_item_catalog import ItemCatalogTestCase

DETECTION = {"match": {"any": [{"id": "svc", "signal": {"name": "SVC_FILE"}}]}}


class ExportTestCase(ItemCatalogTestCase):
    def setUp(self):
        super().setUp()
        self.create_item("t-export", "application", DETECTION)
        self.create_item("t-export-dependent", "application", DETECTION)
        for resolution_id, impact in (("t-export-b", "low"), ("t-export-a", "none")):
            catalog_items.create_resolution("t-export", s.ResolutionCreate(
                id=resolution_id, name=resolution_id, consumer_impact=impact, effort="low",
                description="First line.\nSecond line."), db=self.db)
        catalog_items.create_resolution("t-export-dependent", s.ResolutionCreate(
            id="t-export-dependent-x", name="x", consumer_impact="none", effort="low"), db=self.db)
        self.db.add(models.ResolutionDerivation(
            resolution_id="t-export-a", item_id="t-export", dependent_item_id="t-export-dependent", action="derive",
            dependent_resolution_id="t-export-dependent-x", applies_to="all", reason="Fixture reason."))
        self.db.flush()

    def document(self, item_id="t-export"):
        return yaml.safe_load(catalog_export.export_files(self.db)[f"{item_id}.yaml"])

    def text(self, item_id="t-export"):
        return catalog_export.export_files(self.db)[f"{item_id}.yaml"]


class ExportTests(ExportTestCase):
    def test_an_unchanged_catalog_exports_byte_identically(self):
        first = catalog_export.export_files(self.db)
        self.assertEqual(first, catalog_export.export_files(self.db))
        self.assertEqual(catalog_export.zip_bytes(first), catalog_export.zip_bytes(catalog_export.export_files(self.db)))

    def test_one_file_per_item_holding_its_resolutions_and_their_derivations(self):
        document = self.document()
        self.assertEqual(document["id"], "t-export")
        self.assertEqual([r["id"] for r in document["resolutions"]], ["t-export-a", "t-export-b"])   # sorted
        self.assertEqual(document["resolutions"][0]["derivations"], [{
            "dependent_item_id": "t-export-dependent", "action": "derive", "dependent_resolution_id": "t-export-dependent-x",
            "applies_to": "all", "reason": "Fixture reason.", "deleted": False}])
        self.assertEqual(document["resolutions"][1]["derivations"], [])

    def test_keys_are_sorted_and_multiline_text_is_a_literal_block(self):
        text = self.text()
        top_level = [line.split(":")[0] for line in text.splitlines() if line and not line.startswith((" ", "-"))]
        self.assertEqual(top_level, sorted(top_level))
        self.assertIn("description: |-\n    First line.\n    Second line.", text)

    def test_soft_deleted_rows_are_exported_marked_deleted(self):
        catalog_items.delete_resolution("t-export", "t-export-b", deleted_by="team", db=self.db)
        self.assertTrue(self.document()["resolutions"][1]["deleted"])
        catalog_items.delete_item("t-export-dependent", deleted_by="team", db=self.db)
        self.assertTrue(self.document("t-export-dependent")["deleted"])

    def test_content_only_no_baseline_hash_no_computed_columns_no_engagement_data(self):
        self.db.get(models.CatalogItem, "t-export").seeded_hash = "f" * 64
        item_decisions.upsert_item_decision(TEST_ENGAGEMENT_ID, "t-export", s.EngagementDecisionUpsert(
            resolution_id="t-export-b", rationale="client rationale"), Response(), db=self.db)
        document = self.document()
        self.assertEqual(sorted(document), ["category", "deleted", "description", "detection", "excluded_roles", "id", "name",
                                            "owner_team", "resolutions", "scope", "status"])
        self.assertEqual(sorted(document["resolutions"][1]), [
            "consumer_impact", "container_ready", "deleted", "derivations", "description", "effort", "id", "is_default",
            "linux_compatible", "name", "notes", "status", "target_description"])
        everything = "".join(catalog_export.export_files(self.db).values())
        for absent in ("seeded_hash", "f" * 64, "client rationale", TEST_ENGAGEMENT_ID):
            self.assertNotIn(absent, everything)


class ImportTests(ExportTestCase):
    """Onto a non-empty catalog, import goes through seed_row: never overwrites an edited row."""

    def import_document(self, document):
        files = {f"{document['id']}.yaml": catalog_export.render(document)}
        return catalog_export.import_files(self.db, files)

    def edit_in_ui(self, description):
        item = self.db.get(models.CatalogItem, "t-export")
        catalog_items.update_item("t-export", s.CatalogItemWrite(
            name=item.name, description=description, scope=item.scope, category=item.category, detection=item.detection,
            excluded_roles=item.excluded_roles, owner_team=item.owner_team, status=item.status), db=self.db)

    def test_import_inserts_a_missing_item_with_its_resolutions_and_derivations(self):
        document = copy.deepcopy(self.document())
        document["id"] = "t-export-new"
        for resolution in document["resolutions"]:
            resolution["id"] = resolution["id"].replace("t-export", "t-export-new")
        report = self.import_document(document)
        self.assertEqual(report["mode"], "merge (seed_row)")
        self.assertIn("catalog_items t-export-new", report["inserted"])
        self.assertIn("resolution_derivations t-export-new-a -> t-export-dependent", report["inserted"])
        self.assertEqual(self.document("t-export-new")["resolutions"][0]["derivations"][0]["reason"], "Fixture reason.")

    def test_import_never_overwrites_an_edited_row(self):
        document = self.document()
        # Rows the UI created have no seed baseline: an import that differs is a conflict.
        self.edit_in_ui("The team's wording.")
        changed = {**document, "description": "Wording in the file."}
        report = self.import_document(changed)
        self.assertEqual([(c["row"], c["fields"]) for c in report["conflicts"]],
                         [("t-export", {"description": {"database": "The team's wording.", "seed": "Wording in the file."}})])
        self.assertEqual(self.db.get(models.CatalogItem, "t-export").description, "The team's wording.")

    def test_import_updates_only_rows_not_edited_since_seeded(self):
        first = self.import_document({**self.document(), "description": "Baseline wording."})
        self.assertEqual(first["conflicts"][0]["row"], "t-export")       # UI-created: no baseline yet
        item = self.db.get(models.CatalogItem, "t-export")
        from app.items import baseline
        item.seeded_hash = baseline.digest(baseline.content(item))      # as if seeded
        report = self.import_document({**self.document(), "description": "Updated in the file."})
        self.assertEqual(report["updated"], ["catalog_items t-export"])
        self.assertEqual(item.description, "Updated in the file.")

    def test_a_file_must_be_named_for_its_item(self):
        with self.assertRaises(ValueError):
            catalog_export.import_files(self.db, {"other.yaml": catalog_export.render(self.document())})


class TempExportDirCase(ExportTestCase):
    """Exports go to a temporary directory standing in for catalog/items/ —
    never the repository. No tests of its own."""

    def setUp(self):
        super().setUp()
        catalog_export.clear_cache()
        self.out = Path(tempfile.mkdtemp())
        self.repository_dir = catalog_export.DEFAULT_DIR
        catalog_export.DEFAULT_DIR = self.out

    def tearDown(self):
        catalog_export.DEFAULT_DIR = self.repository_dir
        shutil.rmtree(self.out, ignore_errors=True)
        super().tearDown()

    def changes(self):
        return {c["item_id"]: c["change"] for c in catalog_export.status(self.db)["changes"]}


class StalenessTests(TempExportDirCase):
    """What the master catalog view and the dashboard show: items changed
    since the last export into the repository."""

    def test_an_export_into_the_repository_is_recorded_and_current(self):
        report = catalog_export.write(self.db, self.out)
        self.assertTrue(report["recorded"])
        status = catalog_export.status(self.db)
        self.assertEqual((status["is_current"], status["changed"], status["changes"]), (True, 0, []))
        self.assertEqual(status["current_hash"], status["last_export"]["catalog_hash"])

    def test_an_export_anywhere_else_is_not_recorded(self):
        elsewhere = Path(tempfile.mkdtemp())
        try:
            self.assertFalse(catalog_export.write(self.db, elsewhere)["recorded"])
        finally:
            shutil.rmtree(elsewhere, ignore_errors=True)

    def test_added_edited_and_deleted_items_are_listed(self):
        catalog_export.write(self.db, self.out)
        item = self.db.get(models.CatalogItem, "t-export")
        catalog_items.update_item("t-export", s.CatalogItemWrite(
            name=item.name, description="Edited in the UI.", scope=item.scope, category=item.category, detection=item.detection,
            excluded_roles=item.excluded_roles, owner_team=item.owner_team, status=item.status), db=self.db)
        self.create_item("t-export-added", "application", DETECTION)
        catalog_items.delete_item("t-export-dependent", deleted_by="team", db=self.db)
        self.assertEqual(self.changes(), {"t-export": "edited", "t-export-added": "added", "t-export-dependent": "deleted"})
        status = catalog_export.status(self.db)
        self.assertEqual((status["is_current"], status["changed"]), (False, 3))

    def test_a_resolution_or_derivation_change_marks_its_item_edited(self):
        catalog_export.write(self.db, self.out)
        self.db.get(models.ResolutionDerivation, ("t-export-a", "t-export-dependent")).reason = "Changed."
        self.db.flush()
        self.assertEqual(self.changes(), {"t-export": "edited"})

    def test_re_exporting_makes_it_current_again(self):
        catalog_export.write(self.db, self.out)
        self.create_item("t-export-added", "application", DETECTION)
        self.assertEqual(self.changes(), {"t-export-added": "added"})
        catalog_export.write(self.db, self.out)
        self.assertTrue(catalog_export.status(self.db)["is_current"])

    def test_with_no_export_recorded_every_item_is_listed_as_added(self):
        self.db.query(models.CatalogExport).delete()
        self.db.flush()
        status = catalog_export.status(self.db)
        self.assertIsNone(status["last_export"])
        self.assertFalse(status["is_current"])
        self.assertEqual(status["changed"], self.db.query(models.CatalogItem).count())
        self.assertEqual(set(self.changes().values()), {"added"})


class StatusCacheTests(TempExportDirCase):
    """A poll is a cache read unless a catalog row was written or an export
    ran — whatever process wrote it (the counter is bumped by triggers)."""

    def computed(self):
        return catalog_export._cache["computed"]

    def test_repeated_polls_without_writes_are_cache_reads(self):
        first = catalog_export.cached_status(self.db)
        count = self.computed()
        for _ in range(5):
            self.assertIs(catalog_export.cached_status(self.db), first)
        self.assertEqual(self.computed(), count)

    def test_a_catalog_write_recomputes(self):
        catalog_export.write(self.db, self.out)
        self.assertTrue(catalog_export.cached_status(self.db)["is_current"])
        count = self.computed()
        before = catalog_export.catalog_version(self.db)
        self.create_item("t-export-added", "application", DETECTION)
        self.assertGreater(catalog_export.catalog_version(self.db), before)
        status = catalog_export.cached_status(self.db)
        self.assertEqual(self.computed(), count + 1)
        self.assertEqual([(c["item_id"], c["change"]) for c in status["changes"]], [("t-export-added", "added")])

    def test_an_export_recomputes(self):
        self.create_item("t-export-added", "application", DETECTION)
        catalog_export.write(self.db, self.out)
        self.assertFalse(catalog_export.status(self.db)["changes"])
        self.assertTrue(catalog_export.cached_status(self.db)["is_current"])

    def test_a_bulk_update_bypassing_the_orm_still_recomputes(self):
        catalog_export.write(self.db, self.out)
        catalog_export.cached_status(self.db)
        count = self.computed()
        self.db.execute(text("UPDATE item_resolutions SET notes = 'raw SQL' WHERE id = 't-export-b'"))
        status = catalog_export.cached_status(self.db)
        self.assertEqual(self.computed(), count + 1)
        self.assertEqual([(c["item_id"], c["change"]) for c in status["changes"]], [("t-export", "edited")])


if __name__ == "__main__":
    unittest.main()
