"""Every resolution of every active catalog item has engine guidance, or is on the reviewed allow-list with a reason
(backend/app/seed/data/engine_guidance_allowlist.yaml). Otherwise a client's conversion is the first to find the gap,
saying "no instruction yet" for a change a person decided to make.

The catalog checked is this run's own, imported from the export (catalog/items/) as a new environment is.
"""
import unittest

from sqlalchemy.orm import Session

from app.db import engine
from app.engine.inputs import render
from app.items import guidance_coverage


class GuidanceOrAllowList(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.connection.close()

    def test_every_active_resolution_has_guidance_or_a_reviewed_reason(self):
        rows = guidance_coverage.active_resolutions(self.db)
        self.assertGreater(len(rows), 100)
        self.assertEqual(guidance_coverage.missing(rows), [])

    def test_every_allow_list_entry_still_lacks_guidance_and_has_a_reason(self):
        rows = guidance_coverage.active_resolutions(self.db)
        self.assertEqual(guidance_coverage.stale(rows), [])
        for resolution, reason in render.allowlist().items():
            self.assertGreater(len(reason.strip()), 20, resolution)

    def test_it_fails_when_one_guidance_entry_is_removed(self):
        rows = guidance_coverage.active_resolutions(self.db)
        removed = [(item, res, None if res == "csharp-worker-container" else text) for item, res, text in rows]
        self.assertEqual(guidance_coverage.missing(removed), ["ssis-package/csharp-worker-container"])
        # And an allow-list entry whose guidance is written since is stale.
        written = [(item, res, "Steps." if res == "ldap-protocols" else text) for item, res, text in rows]
        self.assertEqual(guidance_coverage.stale(written), ["ldap-protocols"])


if __name__ == "__main__":
    unittest.main()
