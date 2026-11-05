"""Which suites a change runs (scripts/select_suites.py; scripts/run-suites.ps1 -Since, -Paths, -List).

The rules are checked on a stand-in repository laid out as ours: two steps, one with C# test projects, one with
Python tests and a registration, and the backend test modules that test the scripts. run-suites.ps1 -List is then run on this repository itself, as an import runs it:
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
        (self.root / "backend/tests").mkdir(parents=True)
        for modules in select_suites.SCRIPT_TESTS.values():
            for module in modules:
                (self.root / "backend" / (module.replace(".", "/") + ".py")).write_text("")

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

    def suite(self, *paths: str) -> dict:
        return select_suites.select(list(paths), self.root)["suites"][0]

    def test_the_backend_runs_the_backend_suite(self):
        self.assertEqual(self.names("backend/app/engine/convert.py"), ["backend"])

    def test_a_script_runs_only_its_own_tests(self):
        found = self.suite("scripts/run-suites.ps1", "scripts/select_suites.py")
        self.assertEqual((found["name"], found["modules"]), ("backend tests", ["tests.test_suite_selection"]))
        self.assertEqual(found["why"], "tests.test_suite_selection: a script, and its tests: scripts/run-suites.ps1, "
                                       "scripts/select_suites.py")
        found = self.suite("scripts/update-platform.ps1", "scripts/import-client-changes.ps1")
        self.assertEqual(found["modules"], ["tests.test_update_platform", "tests.test_import_client_changes"])
        self.assertEqual(self.suite("scripts/preflight.py")["modules"], ["tests.test_client_install"])
        # A script no test is named for: the whole backend suite.
        self.assertEqual(self.names("scripts/bootstrap.ps1"), ["backend"])

    def test_one_backend_test_module_runs_alone(self):
        (self.root / "backend/tests/test_toolchain.py").write_text("")
        found = self.suite("backend/tests/test_toolchain.py", "scripts/select_suites.py")
        self.assertEqual(found["modules"], ["tests.test_toolchain", "tests.test_suite_selection"])
        # A test module the change deleted has nothing to run; the reproduce check's own module runs the check.
        self.assertEqual(self.names("backend/tests/test_gone.py"), [])
        self.assertEqual(self.names("backend/tests/reproduce_on_scratch.py"), ["reproduce"])
        # Helpers every test module uses are no single module's: the whole backend suite.
        self.assertEqual(self.names("backend/tests/support.py"), ["backend"])

    def test_the_backend_suite_holds_the_named_test_modules(self):
        found = select_suites.select(["scripts/run-suites.ps1", "backend/app/main.py"], self.root)["suites"]
        self.assertEqual([s["name"] for s in found], ["backend"])
        self.assertIn("(the test modules named): scripts/run-suites.ps1", found[0]["why"])

    def test_every_test_module_named_for_a_script_exists_here(self):
        for script, modules in select_suites.SCRIPT_TESTS.items():
            self.assertTrue((ROOT / script).is_file(), script)
            for module in modules:
                self.assertTrue((ROOT / "backend" / (module.replace(".", "/") + ".py")).is_file(), module)

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

    def test_one_test_module_runs_alone_for_real(self):
        """Not -List: the changed test module runs, alone, in seconds, instead of the whole backend suite."""
        done = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                               str(ROOT / "scripts" / "run-suites.ps1"), "-Paths", "backend/tests/test_platform_seed.py"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("  backend tests: tests.test_platform_seed: a backend test module", done.stdout)
        self.assertIn("== backend tests: passed", done.stdout)
        self.assertIn("All suites passed (1,", done.stdout)

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
