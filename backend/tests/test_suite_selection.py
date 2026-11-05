"""Which suites a change runs (scripts/select_suites.py; scripts/run-suites.ps1 -Since, -Paths, -List).

The rules are checked on a stand-in repository laid out as ours: two steps, one with C# test projects, one with
Python tests and a registration. run-suites.ps1 -List is then run on this repository itself, as an import runs it:
it prints the suites and why, and runs none."""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("select_suites", ROOT / "scripts" / "select_suites.py")
select_suites = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(select_suites)


class Selection(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for project in ("steps/step-003-fingerprinting/tests/Fingerprinting.Tests/Fingerprinting.Tests.csproj",
                        "steps/step-003-fingerprinting/tests/Fingerprinting.Dependencies.Tests/Fingerprinting.Dependencies.Tests.csproj",
                        # build output never counts as a test project
                        "steps/step-003-fingerprinting/tests/Fingerprinting.Tests/obj/Copy.Tests.csproj"):
            (self.root / project).parent.mkdir(parents=True, exist_ok=True)
            (self.root / project).write_text("<Project />\n")
        (self.root / "steps/step-002-solution-discovery/tests").mkdir(parents=True)
        (self.root / "steps/step-002-solution-discovery/tests/__init__.py").write_text("")
        (self.root / "third_party/code-modernization/scripts/tests").mkdir(parents=True)

    def names(self, *paths: str) -> list[str]:
        return [s["name"] for s in select_suites.select(list(paths), self.root)["suites"]]

    def test_a_frontend_only_change_runs_the_frontend_tests_and_type_check(self):
        self.assertEqual(self.names("frontend/src/App.tsx", "frontend/package.json"),
                         ["frontend tests", "frontend type check"])
        why = select_suites.select(["frontend/src/App.tsx"], self.root)["suites"][0]["why"]
        self.assertEqual(why, "the frontend: frontend/src/App.tsx")

    def test_a_step_change_runs_only_that_steps_tests(self):
        self.assertEqual(self.names("steps/step-003-fingerprinting/src/Fingerprinting.Outbound/BackendReach.cs"),
                         ["C# Fingerprinting.Dependencies.Tests", "C# Fingerprinting.Tests"])
        self.assertEqual(self.names("steps/step-002-solution-discovery/discovery/framework.py"),
                         ["step step-002-solution-discovery"])

    def test_a_registration_change_runs_the_seed_and_registration_tests_and_the_reproduce_check(self):
        for path in ("steps/step-002-solution-discovery/registration/solution-discovery.json",
                     "catalog/items/wcf-service.yaml"):
            self.assertEqual(self.names(path), ["seed and registrations", "reproduce"], path)
        # Under backend\ too: the backend suite holds the seed and registration tests, and runs them once.
        self.assertEqual(self.names("backend/app/jobs/phase0-repository-discovery.yaml"), ["backend", "reproduce"])
        self.assertEqual(self.names("backend/alembic/versions/c3e9a7b5d1f4_toolchain_checks.py"), ["backend", "reproduce"])
        self.assertEqual(self.names("backend/app/steps/conversion_preparation.registration.json"), ["backend", "reproduce"])

    def test_a_documentation_only_change_runs_nothing(self):
        found = select_suites.select(["docs/VDI-SETUP.md", "README.md", "steps/step-003-fingerprinting/README.md",
                                      "PLATFORM_SOURCE.json"], self.root)
        self.assertEqual(found["suites"], [])
        self.assertIn("only documentation changed", found["none"])

    def test_the_backend_and_the_scripts_run_the_backend_suite(self):
        self.assertEqual(self.names("backend/app/engine/convert.py"), ["backend"])
        self.assertEqual(self.names("scripts/run-suites.ps1"), ["backend"])

    def test_a_path_no_rule_knows_runs_everything(self):
        self.assertEqual(self.names(".gitignore"),
                         ["backend", "reproduce", "frontend tests", "frontend type check",
                          "C# Fingerprinting.Dependencies.Tests", "C# Fingerprinting.Tests",
                          "step step-002-solution-discovery", "third_party code-modernization"])
        self.assertEqual([s["name"] for s in select_suites.select_all(self.root)["suites"]], self.names(".gitignore"))


@unittest.skipUnless(sys.platform == "win32", "run-suites.ps1 is Windows PowerShell")
class RunSuitesList(unittest.TestCase):
    def run_suites(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                               str(ROOT / "scripts" / "run-suites.ps1"), "-List", *args],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")

    def test_it_prints_the_suites_and_why_and_runs_none(self):
        done = self.run_suites("-Paths", "frontend/src/App.tsx,steps/step-003-fingerprinting/src/X.cs")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Suites to run (4):", done.stdout)
        self.assertIn("  frontend tests: the frontend: frontend/src/App.tsx", done.stdout)
        self.assertIn("  C# Fingerprinting.Tests: step step-003-fingerprinting: steps/step-003-fingerprinting/src/X.cs",
                      done.stdout)
        self.assertNotIn("== ", done.stdout)                     # nothing ran

    def test_documentation_only_runs_nothing_and_passes(self):
        done = self.run_suites("-Paths", "docs/VDI-SETUP.md")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("No suite to run: only documentation changed", done.stdout)

    def test_since_a_commit_takes_the_paths_changed_since_it(self):
        done = self.run_suites("-Since", "HEAD")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("changed since HEAD", done.stdout)
        refused = self.run_suites("-Since", "no-such-commit")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("is not a commit of this repository", refused.stdout)
