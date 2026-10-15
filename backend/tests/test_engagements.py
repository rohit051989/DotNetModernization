"""Creating an engagement: the service the API and the command line share (app/engagements)."""
import contextlib
import io
import unittest
import uuid

from app import models
from app.db import SessionLocal
from app.engagements import cli, service


class CreateTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_creates_with_name_and_target_framework(self):
        engagement_id = f"test-{uuid.uuid4().hex[:8]}"
        e = service.create(self.db, engagement_id, "  Client B ", "net8.0")
        self.assertEqual((e.id, e.client_name, e.target_framework, e.status), (engagement_id, "Client B", "net8.0", "active"))

    def test_rejects_what_the_platform_cannot_use(self):
        cases = [
            (("Bad Id", "Client", "net10.0"), "id", 422),
            (("ok-id", " ", "net10.0"), "client_name", 422),
            (("ok-id", "Client", "net48"), "target_framework", 422),
            (("ok-id", "Client", "netcoreapp3.1"), "target_framework", 422),
            (("ok-id", "Client", "10.0"), "target_framework", 422),
        ]
        for args, field, status in cases:
            with self.assertRaises(service.EngagementError) as ctx:
                service.create(self.db, *args)
            self.assertEqual((ctx.exception.field, ctx.exception.status_code), (field, status), args)

    def test_an_id_in_use_is_a_conflict(self):
        engagement_id = f"test-{uuid.uuid4().hex[:8]}"
        service.create(self.db, engagement_id, "Client", "net10.0")
        with self.assertRaises(service.EngagementError) as ctx:
            service.create(self.db, engagement_id, "Other", "net10.0")
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (409, "DUPLICATE_ID"))

    def test_id_from_name(self):
        self.assertEqual(service.id_from_name("Royal Client — Wave 1"), "royal-client-wave-1")


class CommandLineTests(unittest.TestCase):
    def test_create_then_list(self):
        name = f"Test CLI {uuid.uuid4().hex[:8]}"
        engagement_id = service.id_from_name(name)
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["create", "--name", name, "--target-framework", "net8.0"]), 0)
                self.assertEqual(cli.main(["list"]), 0)
            self.assertIn(f"Created engagement '{engagement_id}': {name}, target framework net8.0", out.getvalue())
            self.assertRegex(out.getvalue(), rf"{engagement_id}\s+net8.0\s+{name}")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(cli.main(["create", "--name", name, "--target-framework", "net8.0"]), 1)
            self.assertIn("already exists", err.getvalue())
        finally:
            with SessionLocal() as db:
                row = db.get(models.Engagement, engagement_id)
                if row is not None:
                    db.delete(row)
                    db.commit()


if __name__ == "__main__":
    unittest.main()
