"""Catalog wording a release corrected reaches an existing catalog (release 7; app/seed/catalog_source.py
WORDING_CORRECTIONS). An installed catalog is the database's own, so a reseed alone would keep an older release's
description that cited a client's findings; the seed applies the corrected items from the export through
baseline.seed_row: an unedited row takes the new wording, an edited one is left and reported.

Runs in this test run's own schema (tests/__init__.py); each test puts the row back as it found it.
Uses stdlib unittest, same rationale as test_repository_ingest.py.
"""

import unittest

from app import models
from app.db import SessionLocal
from app.items import baseline
from app.seed import catalog_source

ITEM = "serilog-file-sink"
OLD = ("A Serilog File sink configured with a Windows drive-letter or UNC path. In the client's assessment, one API "
       "repository has 18 hardcoded Windows paths across 16 appsettings files.")


class WordingCorrectionTests(unittest.TestCase):
    def setUp(self):
        db = SessionLocal()
        row = db.get(models.CatalogItem, ITEM)
        if row is None or catalog_source.choose(db) != "database":
            db.close()
            self.skipTest("the catalog in this schema is not the database's own")
        self.saved = (row.description, row.seeded_hash)
        db.close()

    def tearDown(self):
        db = SessionLocal()
        row = db.get(models.CatalogItem, ITEM)
        row.description, row.seeded_hash = self.saved
        db.commit()
        db.close()

    def stage(self, edited: bool):
        """The row as an older release left it: its old description, seeded (unedited) or changed since (edited)."""
        db = SessionLocal()
        row = db.get(models.CatalogItem, ITEM)
        row.description = OLD
        db.flush()
        seeded = {**baseline.content(row), "description": OLD + (" (an older seed)" if edited else "")}
        row.seeded_hash = baseline.digest(seeded)
        db.commit()
        db.close()

    def description(self) -> str:
        db = SessionLocal()
        try:
            return db.get(models.CatalogItem, ITEM).description
        finally:
            db.close()

    def test_an_unedited_row_takes_the_corrected_wording_on_reseed(self):
        self.stage(edited=False)
        report = catalog_source.seed_from_export_or_database()
        self.assertEqual(report["corrections"]["updated"], [f"catalog_items {ITEM}"])
        self.assertNotIn("client's assessment", self.description())
        self.assertIn("A repository often repeats the same path", self.description())

    def test_an_edited_row_is_left_as_it_is_and_reported(self):
        self.stage(edited=True)
        report = catalog_source.seed_from_export_or_database()
        self.assertEqual([c["row"] for c in report["corrections"]["conflicts"]], [ITEM])
        self.assertEqual(self.description(), OLD)


if __name__ == "__main__":
    unittest.main()
