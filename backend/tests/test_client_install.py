"""Ready for the client's VDI (01-ENVIRONMENT-SETUP.md sections 9 and 10; 36-COPILOT-ENHANCED-CONVERSION Part N):
the database settings and credentials, the scratch schemas, RUNS_DIR, the public-feed switch, sibling detection,
and the conversion's status and Verify refusal. Without .NET.

Run: python -m unittest tests.test_client_install
"""
import datetime
import json
import os
import subprocess
import tempfile
import unittest
import uuid
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

    def test_a_refusal_is_a_short_summary_with_the_full_list_behind_it(self):
        from app.engine.inputs import NotSelfContained, SecretFound
        from app.steps import conversion_preparation

        findings = [{"file": f".github/upgrades/skills/applying-{n}.md", "check": "repository value",
                     "detail": f"the value of K{n} in deploy/SetParam.xml"} for n in range(7)]
        findings.append({"file": ".github/upgrades/skills/applying-0.md", "check": "token", "detail": "line 3"})
        summary, details = conversion_preparation.problem(SecretFound(findings))
        self.assertEqual(summary, "Refused, a generated input would still contain a secret value: 8 finding(s) in 7 "
                                  "file(s). Nothing was written.")
        self.assertEqual(len(details), 8)
        self.assertEqual(details[0], ".github/upgrades/skills/applying-0.md: repository value (the value of K0 in "
                                     "deploy/SetParam.xml)")
        summary, _ = conversion_preparation.problem(NotSelfContained(
            [{"file": "a.md", "line": 3, "check": "platform path", "match": "docs/"}]))
        self.assertIn("not self-contained: 1 finding(s) in 1 file(s)", summary)
        summary, details = conversion_preparation.problem(RuntimeError("first line\n  second\n  third"))
        self.assertEqual((summary, details), ("RuntimeError: first line", ["second", "third"]))

    def test_secret_values_named_by_reference_are_a_warning_and_the_preparation_completes(self):
        from unittest import mock

        from app import models
        from app.db import SessionLocal
        from app.steps import conversion_preparation
        from tests.support import TEST_ENGAGEMENT_ID, CommittedTestEngagement

        db = SessionLocal()
        self.addCleanup(db.close)
        engagement = CommittedTestEngagement(db)
        name = f"Prepare-{uuid.uuid4().hex[:6]}"
        repo = models.Repository(engagement_id=TEST_ENGAGEMENT_ID, name=name, slug=name.lower(), source_type="local_path",
                                 local_path=f"C:\\{name}", local_path_normalised=f"c:\\{name.lower()}",
                                 root_folder_name=name, ingest_status="scanned")
        db.add(repo)
        db.commit()
        self.addCleanup(engagement.remove)
        self.addCleanup(lambda: (db.query(models.Repository).filter_by(id=repo.id).delete(), db.commit()))
        prepared = {"action": "prepared", "number": 1, "branch": "conversion/1", "baseline": "a" * 40, "head": "b" * 40,
                    "baselineFrom": "the commit discovery scanned", "packageStep": {"cycles": 1},
                    "secretReferences": [{"file": ".github/upgrades/skills/applying-move-to-secret.md", "references": 2}]}
        with mock.patch.object(convert, "prepare", return_value=prepared):
            result = conversion_preparation.run(StepContext(
                step_name="conversion-preparation", step_version="1.0.0", job_name="phase0-repository-discovery",
                job_execution_id="x", step_execution_id="y", parameters={"repository_id": str(repo.id)},
                working_dir=".", output_dir=".", database_url=settings.database_url))
        self.assertEqual(result.exit_status, "COMPLETED")
        attempt = json.loads((convert.conversions_dir(TEST_ENGAGEMENT_ID, repo.slug) / conversion_preparation.LAST_PREPARE)
                             .read_text(encoding="utf-8"))
        self.assertEqual(attempt["status"], "prepared")
        self.assertEqual(attempt["warnings"], {
            "summary": "2 secret value(s) named by file, key and line instead of quoted, in 1 generated file(s)",
            "details": [".github/upgrades/skills/applying-move-to-secret.md: 2 reference(s)"]})


def _preflight():
    import importlib.util

    spec = importlib.util.spec_from_file_location("preflight", BACKEND.parent / "scripts" / "preflight.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PreflightVersions(unittest.TestCase):
    """Each tool older than the stated requirement is MISSING, with the requirement in the message."""

    def run_tools(self, outputs: dict[str, tuple[int, str]], python=(3, 13, 1), cfg: dict | None = None):
        from unittest import mock

        pf = _preflight()
        seen = []

        def fake_run(*args):
            seen.append(args)
            name = Path(args[0]).stem.lower() if args[0] else ""
            if name == "dotnet" and args[1:] == ("--version",):
                return outputs.get("dotnet --version", (-1, ""))
            if args[1:2] == ("-c",):       # the interpreter bootstrap uses: version, release level, sys.version, path
                if not python:
                    return (-1, "")
                release = python[3:5] if len(python) > 3 else ("final", 0)
                text = ".".join(map(str, python[:3]))
                return (0, f"{text}\n{release[0]} {release[1]}\n{text}{'' if release[0] == 'final' else 'b2'}\n{args[0]}")
            return outputs.get(name, (-1, ""))

        where = {"npm": "npm", "dotnet": "C:\\Users\\u\\dotnet\\dotnet.exe"}
        # The runtime check reads the real file system; PreflightDotnetRuntime covers it.
        with mock.patch.object(pf, "run", side_effect=fake_run), mock.patch.object(pf.shutil, "which", side_effect=where.get), \
                mock.patch.object(pf, "dotnet_runtime"), mock.patch.object(pf, "tested_python", return_value=self.tested), \
                mock.patch("builtins.print"):
            pf.tools(cfg or {})
        self.interpreters = [a[0] for a in seen if a[1:2] == ("-c",)]
        self.warnings = dict(pf.warnings)
        return {what: (ok, detail) for ok, what, detail in pf.results}

    tested: tuple = ()

    def test_a_pre_release_python_is_refused_with_the_reason(self):
        results = self.run_tools(self.CURRENT, python=(3, 14, 0, "beta", 2))
        ok, detail = results["Python"]
        self.assertFalse(ok)
        self.assertIn("3.14.0b2", detail)
        self.assertIn("is a pre-release (beta 2)", detail)
        self.assertIn("Install the final 3.14.x release", detail)

    def test_an_older_patch_than_the_tested_one_is_a_warning_not_a_failure(self):
        self.tested = (3, 14, 8)
        results = self.run_tools(self.CURRENT, python=(3, 14, 2))
        self.assertTrue(results["Python"][0])
        self.assertIn("older than 3.14.8, the release the full suite passed on", self.warnings["Python"])
        results = self.run_tools(self.CURRENT, python=(3, 14, 8))
        self.assertEqual(self.warnings, {})

    CURRENT = {"node": (0, "v22.12.0"), "npm": (0, "10.9.0"), "git": (0, "git version 2.17.0.windows.1"),
               "dotnet": (0, "10.0.100 [C:\\Program Files\\dotnet\\sdk]"), "dotnet --version": (0, "10.0.100")}

    def test_the_minimums_pass(self):
        results = self.run_tools(self.CURRENT, python=(3, 11, 0))
        self.assertTrue(all(ok for ok, _ in results.values()), results)

    def test_the_client_toolchain_passes(self):
        toolchain = {**self.CURRENT, "dotnet": (0, "10.0.203 [C:\\Users\\u\\dotnet\\sdk]"), "dotnet --version": (0, "10.0.203")}
        results = self.run_tools(toolchain, python=(3, 14, 8), cfg={"PYTHON": "C:\\MP\\tools\\python314\\python.exe"})
        self.assertTrue(all(ok for ok, _ in results.values()), results)
        self.assertEqual(results[".NET SDK"][1], "10.0.203 used, from C:\\Users\\u\\dotnet; installed: 10.0.203 "
                                                 "(any .NET 10 SDK from 10.0.100 needed, steps\\step-003-fingerprinting\\global.json)")
        self.assertEqual(results["Python"][1], "3.14.8 (C:\\MP\\tools\\python314\\python.exe, PYTHON in backend\\.env; "
                                               "3.11.0 to 3.14.x needed)")

    def test_python_on_path_when_python_is_unset(self):
        results = self.run_tools(self.CURRENT, python=(3, 13, 1))
        self.assertEqual(self.interpreters, ["python"])
        self.assertIn("python on PATH", results["Python"][1])

    def test_a_missing_python_says_not_found(self):
        results = self.run_tools(self.CURRENT, python=None)
        self.assertEqual(results["Python"][0], False)
        self.assertIn("python not found", results["Python"][1])

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


class PreflightProxiesAndLock(unittest.TestCase):
    def test_a_source_goes_through_the_proxy_unless_no_proxy_names_it(self):
        pf = _preflight()
        settings = {"HTTPS_PROXY": "http://jdoe:secret@proxy.client.example:8080", "HTTP_PROXY": "",
                    "NO_PROXY": "localhost,.client.example"}
        self.assertEqual(pf.route("https://pypi.org/simple/", settings), "through the proxy http://***@proxy.client.example:8080")
        self.assertEqual(pf.route("https://artifactory.client.example/api/pypi/simple", settings),
                         "direct (NO_PROXY .client.example)")
        self.assertEqual(pf.route("https://pypi.org/simple/", {**settings, "HTTPS_PROXY": ""}), "direct (no proxy set)")
        self.assertEqual(pf.route(r"C:\feeds\local", settings), "a folder: no network")

    def test_a_tools_message_is_shown_with_credentials_masked(self):
        pf = _preflight()
        out = "noise\nERROR: Could not fetch https://jdoe:token@mirror.client.example/simple/pyyaml/\nERROR: 401 Unauthorized"
        self.assertEqual(pf.tail(out, 2), "ERROR: Could not fetch https://***@mirror.client.example/simple/pyyaml/ | "
                                          "ERROR: 401 Unauthorized")

    def test_the_lock_pins_every_requirement_within_its_range_and_records_the_tested_python(self):
        from pip._vendor.packaging.requirements import Requirement
        from pip._vendor.packaging.utils import canonicalize_name

        text = (BACKEND / "requirements.lock").read_text(encoding="utf-8")
        pins = {canonicalize_name(n): v for n, v in
                (l.split("==") for l in text.splitlines() if l and not l.startswith("#"))}
        for line in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                req = Requirement(line)
                name = canonicalize_name(req.name)
                self.assertIn(name, pins, line)
                self.assertIn(pins[name], req.specifier, f"{name} {pins[name]} not in {req.specifier}")
        self.assertRegex(text, r"(?m)^# tested-python: 3\.\d+\.\d+$")


class Heartbeat(unittest.TestCase):
    """One platform backend per machine (app.heartbeat): backends on different machines share the database side by
    side; the row checked is always this machine's."""

    def setUp(self):
        from types import SimpleNamespace

        from app import heartbeat

        self.hb = heartbeat
        self.now = datetime.datetime(2026, 10, 16, 12, 0, tzinfo=datetime.timezone.utc)
        self.mine = heartbeat.Me(uuid.uuid4(), "VDI-1", "jdoe", 100, r"C:\MP\code", 8001)
        self.row = lambda **k: SimpleNamespace(**{"instance_id": uuid.uuid4(), "host": "vdi-1", "os_user": "jdoe",
                                                  "pid": 200, "platform_root": r"C:\MP\code", "api_port": 8001,
                                                  "started_at": self.now, "beat_at": self.now, **k})

    def test_a_second_backend_on_this_machine_refuses_and_says_what_to_do(self):
        reason = self.hb.refusal(self.row(), self.mine, datetime.timedelta(seconds=30), alive=lambda pid: True)
        self.assertIn("already running on this machine (vdi-1)", reason)
        self.assertIn("One backend runs per machine", reason)
        # How long until it expires, and how to clear one known to be stale.
        self.assertIn("expires 90 s after its last beat", reason)
        self.assertIn("start again in 61 s", reason)
        self.assertIn("-m app.heartbeat clear", reason)

    def test_a_restart_takes_over_when_the_recorded_process_is_gone(self):
        fresh = datetime.timedelta(seconds=5)
        self.assertIsNotNone(self.hb.refusal(self.row(), self.mine, fresh, alive=lambda pid: True))
        # A restart, a killed process, or --reload's new worker: the recorded process is gone, so it is taken over.
        self.assertIsNone(self.hb.refusal(self.row(), self.mine, fresh, alive=lambda pid: False))

    def test_a_stale_heartbeat_and_no_heartbeat_are_taken_over(self):
        self.assertIsNone(self.hb.refusal(None, self.mine, None))
        expired = self.hb.STALE + datetime.timedelta(seconds=1)
        self.assertIsNone(self.hb.refusal(self.row(), self.mine, expired, alive=lambda pid: True))
        self.assertIsNotNone(self.hb.refusal(self.row(), self.mine, self.hb.STALE, alive=lambda pid: True))

    def test_this_process_is_alive_and_a_finished_one_is_not(self):
        self.assertTrue(self.hb.pid_alive(os.getpid()))
        child = subprocess.Popen(["cmd", "/c", "exit 0"])
        child.wait()
        self.assertFalse(self.hb.pid_alive(child.pid))


class DeletionNeverFollowsALink(unittest.TestCase):
    def test_a_junction_inside_a_deleted_folder_is_unlinked_and_its_target_kept(self):
        from app.deletion.service import remove_tree

        with tempfile.TemporaryDirectory() as tmp:
            sibling = Path(tmp) / "EnterprisePackages"
            (sibling / "feed").mkdir(parents=True)
            (sibling / "feed" / "package.nupkg").write_text("keep me")
            worktree = Path(tmp) / "runs" / "conversions" / "1" / "wt"
            worktree.mkdir(parents=True)
            (worktree / "Program.cs").write_text("x")
            subprocess.run(["cmd", "/c", "mklink", "/J", str(worktree / "EnterprisePackages"), str(sibling)],
                           check=True, capture_output=True)
            remove_tree(Path(tmp) / "runs")
            self.assertFalse((Path(tmp) / "runs").exists())
            self.assertEqual((sibling / "feed" / "package.nupkg").read_text(), "keep me")


class DotnetRootSetting(unittest.TestCase):
    """DOTNET_ROOT in backend/.env: first on PATH and DOTNET_ROOT for this process and every process it starts."""

    def test_it_is_applied_to_this_process_and_inherited_by_what_it_starts(self):
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "dotnet.exe").write_bytes(b"")
            with mock.patch.dict(os.environ, {"PATH": f"C:\\elsewhere{os.pathsep}{tmp}", "DOTNET_ROOT": ""}):
                config.apply_dotnet_root(Settings(dotnet_root=tmp))
                self.assertEqual(os.environ["DOTNET_ROOT"], tmp)
                self.assertEqual(os.environ["PATH"].split(os.pathsep), [tmp, "C:\\elsewhere"])
                seen = subprocess.run(["cmd", "/c", "echo %DOTNET_ROOT%"], capture_output=True, text=True).stdout.strip()
                self.assertEqual(seen, tmp)

    def test_a_folder_without_dotnet_is_refused_and_unset_changes_nothing(self):
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"PATH": "C:\\x"}):
            with self.assertRaisesRegex(ValueError, "has no dotnet executable"):
                config.apply_dotnet_root(Settings(dotnet_root=tmp))
            config.apply_dotnet_root(Settings(dotnet_root=""))
            self.assertEqual(os.environ["PATH"], "C:\\x")

    def test_a_build_log_names_its_sdk(self):
        from app.conversion import dotnet

        with tempfile.TemporaryDirectory() as tmp:
            header = dotnet.sdk(Path(tmp))
        self.assertRegex(header, r"(?i)^# \.NET SDK \d+\.\d+\.\d+, .*dotnet(\.exe)?$")


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
            self.assertIn(f"Set DOTNET_ROOT={folder.resolve()} in backend\\.env", detail)
            ok, _, detail = self.run_check(folder, str(folder))
            self.assertTrue(ok, detail)
            self.assertIn("10.0.7", detail)


if __name__ == "__main__":
    unittest.main()
