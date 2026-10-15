"""The engine boundary (36-COPILOT-ENHANCED-CONVERSION Part I).

- A client engagement's allowlist defaults to empty.
- Sending code to an engine or LLM provider not on the allowlist is refused — the conversion engine
  (a run cannot start) and the shared LLM provider alike.
- No field, setting or file accepts an engine credential.
- Every run records identity, organisation, model and engine version.

Run: python -m unittest tests.test_engine_boundary
"""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from app import models
from app.config import Settings
from app.db import SessionLocal
from app.engine import allowlist as allowlist_cli
from app.engine import boundary, paths, runs
from tests.support import TEST_ENGAGEMENT_ID, ensure_test_engagement

BACKEND = Path(__file__).resolve().parents[1]
CREDENTIAL_NAME = re.compile(r"(?i)token|secret|password|passwd|credential|api_?key|\bpat\b|bearer")


def _run_args(**over):
    args = dict(engagement_id=TEST_ENGAGEMENT_ID, label="t-boundary-run", provider="github-copilot",
                organisation="acme-corp", identity="jdoe_acme", model="Claude Sonnet 4.5",
                engine_version="GitHub Copilot app modernization 1.0.1", host="Visual Studio 2026 18.3")
    args.update(over)
    return args


class Allowlist(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        self.addCleanup(self.db.rollback)
        self.engagement = ensure_test_engagement(self.db)
        self.engagement.engine_allowlist = []
        self.db.flush()

    def test_a_new_engagement_starts_with_an_empty_allowlist(self):
        fresh = models.Engagement(id="t-engagement-boundary-new", client_name="New client")
        self.db.add(fresh)
        self.db.flush()
        self.db.refresh(fresh)
        self.assertEqual(fresh.engine_allowlist, [])
        for provider in boundary.PROVIDERS:
            with self.assertRaises(boundary.EngineNotAllowed):
                boundary.require_allowed(fresh, provider, "acme-corp")

    def test_the_conversion_engine_is_refused_until_allowed_and_only_under_its_organisation(self):
        with self.assertRaisesRegex(boundary.EngineNotAllowed, "allowlist is empty"):
            boundary.require_allowed(self.engagement, "github-copilot", "acme-corp")
        boundary.allow(self.db, self.engagement, "github-copilot", "acme-corp")
        boundary.require_allowed(self.engagement, "github-copilot", "acme-corp")
        boundary.require_allowed(self.engagement, "github-copilot", "ACME-CORP")
        with self.assertRaisesRegex(boundary.EngineNotAllowed, "allows only: github-copilot under acme-corp"):
            boundary.require_allowed(self.engagement, "github-copilot", "someone-elses-org")
        with self.assertRaises(boundary.EngineNotAllowed):
            boundary.require_allowed(self.engagement, "github-copilot", None)

    def test_the_shared_llm_provider_is_refused_unless_listed(self):
        boundary.allow(self.db, self.engagement, "github-copilot", "acme-corp")
        for provider in ("claude-code", "devin"):
            with self.assertRaises(boundary.EngineNotAllowed):
                boundary.require_allowed(self.engagement, provider)
        boundary.allow(self.db, self.engagement, "claude-code", None)
        boundary.require_allowed(self.engagement, "claude-code")
        with self.assertRaises(boundary.EngineNotAllowed):
            boundary.require_allowed(self.engagement, "devin")

    def test_local_providers_send_nothing_and_need_no_entry(self):
        for provider in boundary.LOCAL_PROVIDERS:
            boundary.require_allowed(self.engagement, provider)

    def test_revoking_refuses_again(self):
        boundary.allow(self.db, self.engagement, "github-copilot", "acme-corp")
        boundary.revoke(self.db, self.engagement, "github-copilot", "acme-corp")
        with self.assertRaises(boundary.EngineNotAllowed):
            boundary.require_allowed(self.engagement, "github-copilot", "acme-corp")

    def test_an_unknown_provider_cannot_be_listed(self):
        with self.assertRaises(ValueError):
            boundary.allow(self.db, self.engagement, "some-cloud-llm", None)

    def test_an_organisation_shaped_like_a_credential_is_refused(self):
        with self.assertRaises(boundary.CredentialRefused):
            boundary.allow(self.db, self.engagement, "github-copilot", "ghp_" + "a" * 36)


class Runs(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        self.addCleanup(self.db.rollback)
        self.engagement = ensure_test_engagement(self.db)
        self.engagement.engine_allowlist = []
        self.db.flush()

    def _count(self):
        return self.db.query(models.EngineRun).filter_by(engagement_id=TEST_ENGAGEMENT_ID).count()

    def test_a_run_on_an_engine_not_on_the_allowlist_is_refused_and_nothing_is_recorded(self):
        before = self._count()
        with self.assertRaises(boundary.EngineNotAllowed):
            runs.start(self.db, **_run_args())
        boundary.allow(self.db, self.engagement, "github-copilot", "acme-corp")
        with self.assertRaises(boundary.EngineNotAllowed):
            runs.start(self.db, **_run_args(organisation="personal-account"))
        self.assertEqual(self._count(), before)

    def test_a_run_records_identity_organisation_model_and_engine_version(self):
        boundary.allow(self.db, self.engagement, "github-copilot", "acme-corp")
        run = runs.start(self.db, **_run_args())
        self.db.refresh(run)
        self.assertEqual((run.signed_in_identity, run.organisation, run.model, run.engine_version),
                         ("jdoe_acme", "acme-corp", "Claude Sonnet 4.5", "GitHub Copilot app modernization 1.0.1"))
        for missing in ("identity", "model", "engine_version"):
            with self.assertRaises(ValueError):
                runs.start(self.db, **_run_args(label="t-boundary-" + missing, **{missing: " "}))

    def test_credential_shaped_values_are_refused_wherever_a_run_takes_text(self):
        boundary.allow(self.db, self.engagement, "github-copilot", "acme-corp")
        shaped = ("ghp_" + "A1" * 18, "github_pat_" + "x" * 30, "sk-ant-" + "k" * 30,
                  "Bearer abcdefghijklmnopqrstuvwx", "password=hunter2", "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0NTY3")
        for value in shaped:
            for field in ("identity", "model", "engine_version", "host"):
                with self.subTest(field=field, value=value[:8]), self.assertRaises(boundary.CredentialRefused) as caught:
                    runs.start(self.db, **_run_args(**{field: value}))
                self.assertNotIn(value, str(caught.exception))                 # never echoed

    def test_inputs_are_hashed_per_file_with_the_runbook(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".github" / "upgrades" / "skills").mkdir(parents=True)
            (root / ".github" / "upgrades" / "skills" / "a.md").write_text("a", encoding="utf-8")
            (root / ".github" / "upgrades" / "dotnet-version-upgrade").mkdir(parents=True)
            (root / ".github" / "upgrades" / "dotnet-version-upgrade" / "plan.md").write_text("engine state", encoding="utf-8")
            (root / ".github" / "copilot-instructions.md").write_text("g", encoding="utf-8")
            (root / "src.cs").write_text("code", encoding="utf-8")
            book = root / "RUNBOOK.md"
            book.write_text("steps", encoding="utf-8")
            got = runs.input_hashes(root, book)
        self.assertEqual([e["path"] for e in got],
                         [".github/copilot-instructions.md", ".github/upgrades/skills/a.md", "runbook:RUNBOOK.md"])
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}", e["sha256"]) for e in got))


DATABASE_LOGIN = {"db_user", "db_password"}


class NoCredentialAnywhere(unittest.TestCase):
    """No field, setting or file accepts an engine credential."""

    def test_no_setting_takes_a_credential(self):
        # The platform's own database login is the one credential a setting holds, from the environment only
        # (01-ENVIRONMENT-SETUP.md section 10); no setting takes an engine's.
        named = [f for f in Settings.model_fields if CREDENTIAL_NAME.search(f)]
        self.assertEqual([f for f in named if f not in DATABASE_LOGIN], [])
        self.assertTrue(set(named) <= DATABASE_LOGIN)

    def test_no_engine_column_takes_a_credential(self):
        for table in (models.EngineRun.__table__, models.Engagement.__table__):
            named = [c.name for c in table.columns if CREDENTIAL_NAME.search(c.name)]
            self.assertEqual(named, [], table.name)

    def test_no_engine_command_line_option_takes_a_credential(self):
        for module in ("app.engine.runs", "app.engine.allowlist"):
            for sub in (["start"], ["intervene"], ["finish"], ["show"]) if module.endswith("runs") else ([],):
                out = subprocess.run([str(BACKEND / ".venv" / "Scripts" / "python.exe"), "-m", module, *sub, "--help"],
                                     cwd=BACKEND, capture_output=True, text=True, timeout=60).stdout
                options = re.findall(r"--[a-z-]+", out)
                self.assertTrue(options, module)
                self.assertEqual([o for o in options if CREDENTIAL_NAME.search(o)], [], (module, sub))

    def test_no_engine_code_reads_a_credential_from_the_environment(self):
        # Passing the environment through to a child process ({**os.environ, ...}) reads nothing; reading a
        # variable does, and no engine code reads one or names a token variable.
        source = "\n".join(p.read_text(encoding="utf-8") for p in (BACKEND / "app" / "engine").rglob("*.py"))
        self.assertNotRegex(source, r"os\.environ\s*\[|os\.environ\.get|getenv|GITHUB_TOKEN|GH_TOKEN|COPILOT_TOKEN")
        self.assertEqual(re.findall(r"os\.environ(?!\s*,)", source.replace("{**os.environ,", "")), [])

    def test_the_allowlist_command_has_no_credential_option(self):
        with self.assertRaises(SystemExit):
            allowlist_cli.main(["allow", "--engagement", TEST_ENGAGEMENT_ID, "--provider", "github-copilot", "--token", "x"])

    def test_engine_state_and_inputs_are_one_definition(self):
        self.assertTrue(paths.is_under(".github/upgrades/dotnet-version-upgrade/plan.md", paths.EXCLUDED_FROM_COMPARISON))
        self.assertTrue(paths.is_under("./.github/skills/x.md", paths.EXCLUDED_FROM_COMPARISON))
        self.assertFalse(paths.is_under(".github/workflows/dotnetcore.yml", paths.EXCLUDED_FROM_COMPARISON))
        self.assertFalse(paths.is_under("src/Web/Program.cs", paths.EXCLUDED_FROM_COMPARISON))


if __name__ == "__main__":
    unittest.main()
