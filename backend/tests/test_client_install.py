"""Ready for the client's VDI (01-ENVIRONMENT-SETUP.md sections 9 and 10; 36-COPILOT-ENHANCED-CONVERSION Part N):
the database settings and credentials, the scratch schemas, RUNS_DIR, the public-feed switch, sibling detection,
and the conversion's status and Verify refusal. Without .NET.

Run: python -m unittest tests.test_client_install
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from app import config
from app.config import Settings, settings
from app.db import scrub
from app.engine import convert, siblings
from app.workflow.contract import StepContext
from app.workflow.runtime import executor

BACKEND = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


class DatabaseSettings(unittest.TestCase):
    def test_the_url_carries_no_credential_and_names_the_schema(self):
        url = config.database_url("modplatform", settings)
        self.assertTrue(url.startswith(f"postgresql+psycopg://{settings.db_host}:{settings.db_port}/{settings.db_name}?"))
        self.assertIn("options=-csearch_path%3Dmodplatform", url)
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        self.assertIsNone(parts.username)          # no user information at all
        self.assertIsNone(parts.password)
        if settings.db_password:
            self.assertNotIn(settings.db_password.get_secret_value(), url)

    def test_a_schema_name_is_a_plain_identifier(self):
        with self.assertRaises(ValueError):
            config.database_url("public; drop table x", settings)
        with self.assertRaises(ValueError):
            Settings(db_name="x", runs_dir="C:/elsewhere", db_schema="Bad-Name")

    def test_a_database_url_with_credentials_is_refused(self):
        os.environ["DATABASE_URL"] = "postgresql://u:p@h/d"
        try:
            with self.assertRaisesRegex(ValueError, "DATABASE_URL is no longer read"):
                Settings()
        finally:
            del os.environ["DATABASE_URL"]

    def test_errors_never_show_the_username_or_password(self):
        if not settings.secrets():
            self.skipTest("no credentials configured")
        text = "FATAL: password authentication failed for user \"" + settings.secrets()[0] + "\""
        self.assertNotIn(settings.secrets()[0], scrub(text))
        self.assertIn("***", scrub(text))

    def test_runs_dir_inside_the_repository_is_refused(self):
        inside = Settings(db_name="x", runs_dir=str(BACKEND / "runs"))
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            _ = inside.runs_path
        self.assertFalse(settings.runs_path.is_relative_to(BACKEND.parent))

    def test_dotnet_contacts_nothing_of_its_own_accord(self):
        for name, value in config.QUIET_DOTNET.items():
            self.assertIn(name, os.environ)
        self.assertEqual(os.environ["DOTNET_GENERATE_ASPNET_CERTIFICATE"], "false")


class StepSettings(unittest.TestCase):
    def test_a_step_reads_only_the_settings_it_may(self):
        resolved = executor._resolve_config({"compare_public_feed": "${settings.compare_public_nuget_feed}"}, {})
        self.assertEqual(resolved, {"compare_public_feed": settings.compare_public_nuget_feed})
        for refused in ("${settings.db_password}", "${settings.runs_dir}", "${settings.db_user}"):
            with self.assertRaises(ValueError):
                executor._resolve_config(refused, {})


class SiblingDetection(unittest.TestCase):
    def test_a_relative_feed_beside_the_repository_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            repo = parent / "App"
            (parent / "EnterprisePackages" / "feed").mkdir(parents=True)
            repo.mkdir()
            _git(repo, "init", "-q")
            (repo / "nuget.config").write_text(
                '<configuration><packageSources><clear />'
                '<add key="nuget.org" value="https://api.nuget.org/v3/index.json" />'
                '<add key="internal" value="../EnterprisePackages/feed" />'
                '<add key="missing" value="../Nowhere/feed" />'
                '<add key="inside" value="./local-feed" /></packageSources></configuration>')
            _git(repo, "add", "-A")
            self.assertEqual(siblings.detect(repo), ["EnterprisePackages"])


class ConversionStatus(unittest.TestCase):
    def _conversion(self, tmp: Path) -> dict:
        repo = tmp / "wt"
        repo.mkdir()
        _git(repo, "init", "-q")
        (repo / "a.txt").write_text("a")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "inputs")
        return {"number": 1, "engagement": "e", "repository": "r", "branch": "conversion/1", "worktree": str(repo),
                "head": _git(repo, "rev-parse", "HEAD")}

    def test_prepared_then_refused_then_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._conversion(Path(tmp))
            self.assertEqual(convert.status(rec)["state"], "prepared")
            self.assertIn("nothing beyond its inputs", convert.verify_refusal(rec))
            (Path(rec["worktree"]) / "a.txt").write_text("changed by the engine")
            self.assertIn("uncommitted change", convert.verify_refusal(rec))
            _git(Path(rec["worktree"]), "commit", "-qam", "engine change")
            self.assertEqual(convert.status(rec)["state"], "run")
            self.assertIsNone(convert.verify_refusal(rec))


class PrepareStep(unittest.TestCase):
    def test_it_prepares_nothing_when_told_not_to(self):
        from app.steps import conversion_preparation

        result = conversion_preparation.run(StepContext(
            step_name="conversion-preparation", step_version="1.0.0", job_name="phase0-repository-discovery",
            job_execution_id="x", step_execution_id="y", parameters={"prepare_conversion": False, "repository_id": "z"},
            working_dir=".", output_dir=".", database_url=settings.database_url))
        self.assertEqual(result.exit_status, "NOOP")


if __name__ == "__main__":
    unittest.main()
