"""The Surface section's inbound read — 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md Parts B4
and D.

stdlib unittest; every test runs in one rolled-back transaction, so nothing
persists. Needs the database migrated; the consistency test needs at least one
repository step 4 has run for (skipped otherwise).

Run from backend/:  python -m unittest tests.test_entry_points -v
"""

import unittest
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models
from app.db import engine
from app.routers import surface


class EntryPointReadTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.connection.close()

    def test_unknown_repository_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            surface.get_repository_entry_points(uuid.uuid4(), db=self.db)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_repository_step_4_has_not_run_for_is_409(self):
        scanned = self.db.query(models.EntryPointScan).first()
        if scanned is None:
            self.skipTest("step 4 has not run for any repository")
        self.db.delete(scanned)
        self.db.flush()
        with self.assertRaises(HTTPException) as ctx:
            surface.get_repository_entry_points(scanned.repository_id, db=self.db)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_summary_agrees_with_the_rows(self):
        scan = self.db.query(models.EntryPointScan).first()
        if scan is None:
            self.skipTest("step 4 has not run for any repository")
        result = surface.get_repository_entry_points(scan.repository_id, db=self.db)

        rows = self.db.query(models.EntryPoint).filter_by(repository_id=scan.repository_id).all()
        entries = [e for p in result.projects for e in p.entry_points]
        self.assertEqual(result.entry_point_count, len(rows))
        self.assertEqual({e.id for e in entries}, {r.id for r in rows})
        self.assertEqual(result.no_declared_authentication_count, sum(1 for r in rows if r.auth_declared == "none_declared"))
        self.assertIn("not visible to static analysis", result.auth_declared_scope)
        # Request entry points and lifecycle hooks partition the whole; only
        # request entry points carry authentication, so only they can count.
        self.assertEqual(result.request_entry_point_count + result.lifecycle_hook_count, result.entry_point_count)
        self.assertTrue(all(r.auth_declared is None for r in rows if r.entry_class == "lifecycle"))
        self.assertEqual(
            result.no_declared_authentication_count,
            sum(1 for r in rows if r.entry_class == "request" and r.auth_declared == "none_declared"),
        )
        for project in result.projects:
            self.assertEqual(
                project.no_declared_authentication_count,
                sum(1 for e in project.entry_points if e.auth_declared == "none_declared"),
            )
            self.assertEqual(sum(project.count_by_kind.values()), len(project.entry_points))
            # Skipped projects are listed, with no entry points.
            if project.status != "SCANNED":
                self.assertEqual(project.entry_points, [])
                self.assertIsNotNone(project.skip_reason)
        # Every HTTP row's detail is the http block; a conventional route has no template.
        for entry in entries:
            if entry.kind in ("http_controller_action", "http_minimal_api", "razor_page"):
                self.assertIn("verb", entry.detail)
                if entry.detail["routing"] == "conventional":
                    self.assertIsNone(entry.detail["routeTemplate"])


class CapabilityManifestTests(unittest.TestCase):
    def test_manifest_lists_every_kind_the_table_accepts(self):
        from app.db import SessionLocal
        from app.surface.capabilities import manifest_with_estate_counts

        db = SessionLocal()
        try:
            manifest = manifest_with_estate_counts(db)
        finally:
            db.close()
        self.assertEqual(sorted(k.kind for k in manifest.kinds), sorted(models.ENTRY_POINT_KIND))
        self.assertTrue(manifest.not_covered)
        self.assertIn("not visible to static analysis", manifest.auth_declared_scope)


if __name__ == "__main__":
    unittest.main()
