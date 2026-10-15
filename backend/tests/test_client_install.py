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


def _preflight():
    import importlib.util

    spec = importlib.util.spec_from_file_location("preflight", BACKEND.parent / "scripts" / "preflight.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PreflightVersions(unittest.TestCase):
    """Each tool older than the stated requirement is MISSING, with the requirement in the message."""

    def run_tools(self, outputs: dict[str, tuple[int, str]], python=(3, 13, 1)):
        from unittest import mock

        pf = _preflight()

        def fake_run(*args):
            return outputs.get(Path(args[0]).stem.lower() if args[0] else "", (-1, ""))

        # The runtime check reads the real file system; PreflightDotnetRuntime covers it.
        with mock.patch.object(pf, "run", side_effect=fake_run), mock.patch.object(pf.shutil, "which", return_value="npm"), \
                mock.patch.object(pf.sys, "version_info", python), mock.patch.object(pf, "dotnet_runtime"), \
                mock.patch("builtins.print"):
            pf.tools()
        return {what: (ok, detail) for ok, what, detail in pf.results}

    CURRENT = {"node": (0, "v22.12.0"), "npm": (0, "10.9.0"), "git": (0, "git version 2.17.0.windows.1"),
               "dotnet": (0, "10.0.100 [C:\\Program Files\\dotnet\\sdk]")}

    def test_the_minimums_pass(self):
        results = self.run_tools(self.CURRENT, python=(3, 11, 0))
        self.assertTrue(all(ok for ok, _ in results.values()), results)

    def test_the_client_toolchain_passes(self):
        results = self.run_tools({**self.CURRENT, "dotnet": (0, "10.0.203 [C:\\Users\\u\\dotnet\\sdk]")}, python=(3, 14, 8))
        self.assertTrue(all(ok for ok, _ in results.values()), results)
        self.assertEqual(results[".NET SDK"][1], "10.0.203 (any .NET 10 SDK from 10.0.100 needed, steps\\step-003-fingerprinting\\global.json)")

    def test_any_net10_feature_band_fits_and_nothing_else(self):
        pf = _preflight()
        for installed, ok in [("10.0.100", True), ("10.0.203", True), ("10.0.302", True), ("10.0.400", True),
                              ("9.0.316", False), ("11.0.100", False), ("10.0.100-rc.2.25502.107", False)]:
            self.assertEqual(pf.sdk_fits(installed, "10.0.100", "latestFeature"), ok, installed)

    def test_anything_older_fails_clearly(self):
        older = {"node": (0, "v20.18.1"), "npm": (0, "6.14.18"), "git": (0, "git version 2.16.2"),
                 "dotnet": (0, "9.0.316 [x]\n10.0.100-rc.2.25502.107 [x]")}
        results = self.run_tools(older, python=(3, 10, 11))
        for what, needed in [("Python", "3.11.0 to 3.14.x needed"), ("Node.js", "20.19.0 or a later 20.x, or 22.12.0 or later"),
                             ("npm", "7.0.0 or later"), ("git", "2.17.0 or later"), (".NET SDK", "any .NET 10 SDK from 10.0.100 needed")]:
            ok, detail = results[what]
            self.assertFalse(ok, what)
            self.assertIn(needed, detail, what)
        self.assertIn("too old", results["Node.js"][1])

    def test_node_21_and_python_315_are_refused(self):
        results = self.run_tools({**self.CURRENT, "node": (0, "v21.7.3")}, python=(3, 15, 0))
        self.assertFalse(results["Node.js"][0])
        self.assertFalse(results["Python"][0])
        self.assertIn("too new", results["Python"][1])

    def test_a_missing_tool_says_not_found(self):
        results = self.run_tools({k: v for k, v in self.CURRENT.items() if k != "git"})
        self.assertEqual(results["git"], (False, "not found (2.17.0 or later needed)"))


class PreflightPackageSources(unittest.TestCase):
    """An empty .env key means the tool's own configuration (pip.ini, .npmrc, NuGet.Config), not the public default."""

    def test_the_tools_own_configuration_is_checked_when_the_key_is_empty(self):
        from unittest import mock

        pf = _preflight()

        def fake_run(*args):
            if "pip" in args:
                return 0, "https://mirror.example/api/pypi/pypi/simple"
            if "nuget" in args:
                return 0, "E https://mirror.example/api/nuget/v3/nuget-remote/index.json\nD https://api.nuget.org/v3/index.json"
            return 1, ""

        with mock.patch.object(pf, "run", side_effect=fake_run):
            self.assertEqual(pf.tool_sources("PIP_INDEX_URL"), (["https://mirror.example/api/pypi/pypi/simple"], "pip configuration"))
            self.assertEqual(pf.tool_sources("NUGET_SOURCES"),
                             (["https://mirror.example/api/nuget/v3/nuget-remote/index.json"], "NuGet configuration"))
        with mock.patch.object(pf, "run", return_value=(1, "")), mock.patch.object(pf.shutil, "which", return_value=None):
            self.assertEqual(pf.tool_sources("NPM_REGISTRY"), (["https://registry.npmjs.org/"], "default"))


class PreflightDotnetRuntime(unittest.TestCase):
    """A per-user SDK's runtime is found by the step programs only through DOTNET_ROOT."""

    def run_check(self, dotnet_folder: Path, dotnet_root: str | None):
        from unittest import mock

        pf = _preflight()
        env = {k: v for k, v in os.environ.items() if k != "DOTNET_ROOT"}
        if dotnet_root is not None:
            env["DOTNET_ROOT"] = dotnet_root
        with mock.patch.object(pf.shutil, "which", return_value=str(dotnet_folder / "dotnet.exe")), \
                mock.patch.dict(pf.os.environ, env, clear=True), mock.patch("builtins.print"):
            pf.dotnet_runtime("10.0.100")
        return pf.results[-1]

    def test_a_per_user_sdk_needs_dotnet_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "shared" / "Microsoft.NETCore.App" / "10.0.7").mkdir(parents=True)
            ok, _, detail = self.run_check(folder, None)
            self.assertFalse(ok)
            self.assertIn(f"Set DOTNET_ROOT to {folder.resolve()}", detail)
            ok, _, detail = self.run_check(folder, str(folder))
            self.assertTrue(ok, detail)
            self.assertIn("10.0.7", detail)


if __name__ == "__main__":
    unittest.main()
