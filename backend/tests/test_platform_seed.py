"""Platform configuration from the repository — app/seed/platform.py.

Step registrations and job definitions are seeded from files, never
downgrading or overwriting what this machine has (CLAUDE.md rule 10). Each
test edits the rows of this run's own schema (tests/__init__.py), seeded from
the repository, inside one rolled-back transaction to stage the case; nothing
persists. Before release 7 they edited the live rows, and "an unchanged
machine is a no-op" failed whenever the live database and the repository's
files differed, such as between editing a registration and reseeding. The end-to-end proof is
`python -m app.seed.reproduce` (a scratch database seeded from the
repository alone, compared with this one).

Run from backend/:  python -m unittest tests.test_platform_seed -v
"""

import unittest

from sqlalchemy.orm import Session

from app import models
from app.db import engine
from app.seed import platform
from app.workflow.definition import service as definitions


class PlatformSeedTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")
        if self.db.get(models.WfStepRegistration, "item-detection") is None:
            self.skipTest("lifecycle steps not seeded in this database")

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.connection.close()

    def step(self, name="item-detection"):
        return self.db.get(models.WfStepRegistration, name)


class RegistrationTests(PlatformSeedTestCase):
    def test_every_implemented_step_on_this_machine_has_a_registration_file(self):
        names = {platform.json.loads(p.read_text(encoding="utf-8"))["step_name"] for p in platform.registration_files()}
        implemented = {r.step_name for r in self.db.query(models.WfStepRegistration).filter(
            models.WfStepRegistration.implementation_status == "implemented", models.WfStepRegistration.deleted_at.is_(None))}
        self.assertEqual(implemented - names, set())

    def test_a_stub_is_registered_from_its_file(self):
        row = self.step()
        row.implementation_status, row.adapter_type, row.adapter_config = "stub", "stub", {"exit_status": "NOT_IMPLEMENTED"}
        self.db.flush()
        report = platform.seed_step_registrations(self.db)
        self.assertEqual([r.split(" ")[0] for r in report["registered"]], ["item-detection"])
        self.assertEqual((self.step().adapter_type, self.step().implementation_status), ("python", "implemented"))

    def test_this_machine_newer_than_the_repository_is_never_downgraded(self):
        self.step().version = "9.0.0"
        self.db.flush()
        report = platform.seed_step_registrations(self.db)
        self.assertEqual(len(report["repository_behind"]), 1)
        self.assertIn("live 9.0.0", report["repository_behind"][0])
        self.assertEqual(self.step().version, "9.0.0")

    def test_same_version_different_content_is_a_conflict_left_as_is(self):
        self.step().adapter_config = {"entrypoint": "app.steps.somewhere_else:run"}
        self.db.flush()
        report = platform.seed_step_registrations(self.db)
        self.assertEqual(len(report["conflicts"]), 1)
        self.assertIn("adapter_config", report["conflicts"][0])
        self.assertEqual(self.step().adapter_config, {"entrypoint": "app.steps.somewhere_else:run"})

    def test_an_unchanged_machine_is_a_no_op(self):
        report = platform.seed_step_registrations(self.db)
        self.assertEqual((report["registered"], report["upgraded"], report["conflicts"]), ([], [], []))


class JobDefinitionTests(PlatformSeedTestCase):
    JOB = "phase0-repository-discovery"

    def active(self):
        return definitions.get_active_definition(self.db, self.JOB)

    def test_an_unchanged_machine_is_a_no_op(self):
        report = platform.seed_job_definitions(self.db)
        self.assertEqual((report["stored"], report["activated"], report["conflicts"]), ([], [], []))

    def test_the_repository_version_is_activated_when_nothing_is_active(self):
        version = self.active().version
        self.active().is_active = False
        self.db.flush()
        report = platform.seed_job_definitions(self.db)
        self.assertIn(f"{self.JOB} v{version} ({self.JOB}.yaml)", report["activated"])
        self.assertEqual(self.active().version, version)

    def test_a_stored_version_with_different_content_is_a_conflict(self):
        self.active().checksum = "0" * 64
        self.db.flush()
        report = platform.seed_job_definitions(self.db)
        self.assertEqual(len(report["conflicts"]), 1)


class CatalogSourceTests(PlatformSeedTestCase):
    """The bootstrap order: the export for an empty catalog, the database's
    own catalog when it is not empty, the factory YAML only with no export."""

    def with_export_dir(self, path):
        import os

        previous = os.environ.get("CATALOG_EXPORT_DIR")
        os.environ["CATALOG_EXPORT_DIR"] = str(path)
        self.addCleanup(lambda: os.environ.pop("CATALOG_EXPORT_DIR") if previous is None
                        else os.environ.__setitem__("CATALOG_EXPORT_DIR", previous))

    def test_no_export_means_factory_defaults(self):
        import tempfile

        from app.seed import catalog_source

        self.with_export_dir(tempfile.mkdtemp())
        self.assertEqual(catalog_source.choose(self.db), "factory")

    def test_an_export_and_a_populated_catalog_leave_the_database_authoritative(self):
        from app.items import catalog_export
        from app.seed import catalog_source

        self.with_export_dir(catalog_export.DEFAULT_DIR)
        if not catalog_source.export_exists():
            self.skipTest("no catalog export in this repository")
        self.assertEqual(catalog_source.choose(self.db), "database")

    def test_an_export_and_an_empty_catalog_bootstrap_from_the_export(self):
        from app.items import catalog_export
        from app.seed import catalog_source

        self.with_export_dir(catalog_export.DEFAULT_DIR)
        if not catalog_source.export_exists():
            self.skipTest("no catalog export in this repository")

        class EmptyCatalog:
            """A session whose catalog has no rows — a new environment."""

            def query(self, *_):
                return self

            def first(self):
                return None

        self.assertEqual(catalog_source.choose(EmptyCatalog()), "export")


if __name__ == "__main__":
    unittest.main()
