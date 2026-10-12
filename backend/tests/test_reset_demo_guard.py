"""The demo reset clears every engagement and repository. The platform ships to
each client as code and a client's data lives only in that client's database,
so the reset refuses unless the deployment is explicitly a demo
(DEPLOYMENT=demo). It must refuse before it opens the database.

Run from backend/:  python -m unittest tests.test_reset_demo_guard -v
"""

import unittest
from unittest import mock

from app.seed import reset_demo


class DemoGuardTests(unittest.TestCase):
    def test_only_an_explicit_demo_may_be_reset(self):
        self.assertIsNone(reset_demo.demo_refusal("demo"))
        for deployment in ("client", "", "Demo", "demo "):
            self.assertIn("not 'demo'", reset_demo.demo_refusal(deployment))

    def test_a_client_deployment_is_refused_before_the_database_is_touched(self):
        never = mock.Mock(side_effect=AssertionError("the database was opened"))
        for argv in (["reset_demo", "--yes"], ["reset_demo", "--yes", "--force"], ["reset_demo", "--preflight-only"]):
            with mock.patch.object(reset_demo.settings, "deployment", "client"), \
                    mock.patch.object(reset_demo, "SessionLocal", never), mock.patch("sys.argv", argv):
                self.assertEqual(4, reset_demo.main(), argv)
        never.assert_not_called()

    def test_the_default_deployment_is_a_clients(self):
        from app.config import Settings
        self.assertEqual("client", Settings.model_fields["deployment"].default)


if __name__ == "__main__":
    unittest.main()
