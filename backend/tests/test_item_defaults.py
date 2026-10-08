"""Exactly one default resolution per active item — app/items/defaults.py,
the API guards in app/routers/catalog_items.py, and the deferred constraint
trigger trg_item_resolutions_one_default (migration b3e1c7a2d9f4).

Hermetic: fixture items inside one rolled-back transaction. The API commits
to a savepoint, so the deferred trigger is forced with SET CONSTRAINTS ALL
IMMEDIATE where a test needs it.

Run from backend/:  python -m unittest tests.test_item_defaults -v
"""

import unittest

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import models
from app.items import defaults, pattern_migration
from app.items import schemas as s
from app.routers import catalog_items
from tests.test_item_catalog import ItemCatalogTestCase

DETECTION = {"match": {"all": [{"signal": {"name": "SVC_FILE"}}]}}


class DefaultsTests(ItemCatalogTestCase):
    def setUp(self):
        super().setUp()
        self.create_item("t-defaults", "application", DETECTION)

    def resolution(self, rid, is_default=False, impact="low", status="active"):
        return catalog_items.create_resolution("t-defaults", s.ResolutionCreate(
            id=rid, name=rid, consumer_impact=impact, effort="low", is_default=is_default, status=status), db=self.db)

    def write(self, rid, **changes):
        row = self.db.get(models.ItemResolution, rid)
        fields = {f: getattr(row, f) for f in ("name", "description", "target_description", "consumer_impact", "effort",
                                               "is_default", "linux_compatible", "container_ready", "notes", "status")}
        return catalog_items.update_resolution("t-defaults", rid, s.ResolutionWrite(**{**fields, **changes}), db=self.db)

    def test_the_first_resolution_becomes_the_default(self):
        self.assertTrue(self.resolution("t-defaults-a").is_default)
        self.assertFalse(self.resolution("t-defaults-b").is_default)
        self.assertEqual([], [v for v in defaults.violations(self.db) if v["item_id"] == "t-defaults"])

    def test_the_default_cannot_be_unset_deprecated_or_deleted_while_others_remain(self):
        self.resolution("t-defaults-a")
        self.resolution("t-defaults-b")
        self.assert_http(409, "DEFAULT_REQUIRED", self.write, "t-defaults-a", is_default=False)
        self.assert_http(409, "DEFAULT_REQUIRED", self.write, "t-defaults-a", status="deprecated")
        self.assert_http(409, "DEFAULT_REQUIRED", catalog_items.delete_resolution, "t-defaults", "t-defaults-a", deleted_by=None, db=self.db)
        # Moving the default first makes it an ordinary resolution.
        catalog_items.make_default("t-defaults", "t-defaults-b", db=self.db)
        catalog_items.delete_resolution("t-defaults", "t-defaults-a", deleted_by=None, db=self.db)
        # The last resolution can go: an item with none has nothing to default to.
        catalog_items.delete_resolution("t-defaults", "t-defaults-b", deleted_by=None, db=self.db)
        self.assertEqual([], [v for v in defaults.violations(self.db) if v["item_id"] == "t-defaults"])

    def test_restoring_into_an_item_without_a_default_makes_it_the_default(self):
        self.resolution("t-defaults-a")
        catalog_items.delete_resolution("t-defaults", "t-defaults-a", deleted_by=None, db=self.db)
        self.db.get(models.ItemResolution, "t-defaults-a").is_default = False
        self.db.flush()
        catalog_items.restore_resolution("t-defaults", "t-defaults-a", db=self.db)
        self.assertTrue(self.db.get(models.ItemResolution, "t-defaults-a").is_default)

    def test_the_database_refuses_an_item_left_without_a_default(self):
        self.resolution("t-defaults-a")
        self.resolution("t-defaults-b")
        self.db.get(models.ItemResolution, "t-defaults-a").is_default = False   # bypassing the API
        self.db.flush()
        self.assertEqual(["t-defaults"], [v["item_id"] for v in defaults.violations(self.db) if v["item_id"] == "t-defaults"])
        with self.assertRaises(ValueError):
            defaults.check(self.db, "test")
        with self.assertRaises(IntegrityError) as caught:
            self.db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertIn("exactly one live, active default", str(caught.exception))


class CatalogDefaultsTests(unittest.TestCase):
    def test_the_two_items_without_a_recommendation_have_factory_defaults(self):
        self.assertEqual({"aspnet-webforms": "aspnetcore-mvc-rewrite", "ssis-package": "csharp-sql-pushdown"},
                         pattern_migration.DEFAULT_AMENDMENTS)

    def test_every_active_item_in_this_database_has_exactly_one_default(self):
        from app.db import SessionLocal

        db = SessionLocal()
        try:
            self.assertEqual([], defaults.violations(db))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
