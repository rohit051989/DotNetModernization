"""Which suites a change runs (scripts/select_suites.py; scripts/run-suites.ps1 -Since, -Paths, -List).

The rules are checked on a stand-in repository laid out as ours: two steps, one with C# test projects, one with
Python tests and a registration, and the backend test modules that test the scripts. run-suites.ps1 -List is then run on this repository itself, as an import runs it:
it prints the suites and why, and runs none."""
import importlib.util
import json
import os
import shutil
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

    def test_the_quick_tier_is_the_default_and_full_runs_every_suite(self):
        quick = self.run_suites("-Paths", "frontend/src/App.tsx")
        self.assertIn("Tier: quick (the backend tests marked slow are left out", quick.stdout)
        full = self.run_suites("-Full")
        self.assertEqual(full.returncode, 0, full.stdout + full.stderr)
        self.assertIn("Tier: full.", full.stdout)
        self.assertIn("  backend: every suite", full.stdout)
        both = self.run_suites("-Full", "-Since", "HEAD")
        self.assertEqual(both.returncode, 1)
        self.assertIn("-Full runs every suite", both.stdout)


_shards_spec = importlib.util.spec_from_file_location("backend_shards", ROOT / "scripts" / "backend_shards.py")
backend_shards = importlib.util.module_from_spec(_shards_spec)
_shards_spec.loader.exec_module(backend_shards)


class ShardPlan(unittest.TestCase):
    """scripts/backend_shards.py spreads the modules over the shards by last run's durations, longest first."""

    def test_longest_first_onto_the_least_loaded_shard(self):
        durations = {"tests.a": 600, "tests.b": 300, "tests.c": 280, "tests.d": 20, "tests.e": 10}
        groups = backend_shards.plan(list(durations), 2, durations)
        self.assertEqual(groups, [["tests.a", "tests.e"], ["tests.b", "tests.c", "tests.d"]])

    def test_a_module_with_no_duration_counts_as_the_median_and_no_shard_is_empty(self):
        groups = backend_shards.plan(["tests.a", "tests.new"], 4, {"tests.a": 5, "tests.b": 1, "tests.c": 3})
        self.assertEqual(sorted(groups), [["tests.a"], ["tests.new"]])
        self.assertEqual(backend_shards.plan([], 4, {}), [])

    def test_a_splittable_module_longer_than_a_shares_runs_in_parts_and_each_test_in_exactly_one(self):
        durations = {"tests.long": 900, "tests.a": 300, "tests.b": 300}
        groups = backend_shards.plan(list(durations), 3, durations, {"tests.long"})
        units = sorted(u for g in groups for u in g)
        # A share is 1500 / 3 = 500 s: the 900 s module runs in two parts of 450 s.
        self.assertEqual(units, ["tests.a", "tests.b", "tests.long#1/2", "tests.long#2/2"])
        self.assertEqual(backend_shards.plan(list(durations), 3, durations, set()),
                         [["tests.long"], ["tests.a"], ["tests.b"]])               # not splittable: whole

        class Case:
            def __init__(self, name):
                self.name = name

            def id(self):
                return f"tests.long.Long.{self.name}"
        cases = [Case(f"test_{n:02d}") for n in range(11)]                      # some listed, most not
        parts = [backend_shards._part(cases, k, 3) for k in (1, 2, 3)]
        ran = sorted(c.id() for part in parts for c in part)
        self.assertEqual(ran, sorted(c.id() for c in cases))                    # every test once, in one part
        self.assertTrue(all(parts))
        self.assertEqual(parts, [backend_shards._part(cases, k, 3) for k in (1, 2, 3)])   # the same in every worker

    def test_every_module_of_the_suite_is_planned_once(self):
        every = backend_shards.modules_of_suite()
        self.assertIn("tests.test_suite_selection", every)
        planned = [m for g in backend_shards.plan(every, 6, backend_shards.known_durations(), backend_shards.splittable())
                   for m in g]
        self.assertEqual(sorted({m.split("#")[0] for m in planned}), every)
        self.assertEqual(len([m for m in planned if "#" not in m]), len({m for m in planned if "#" not in m}))

    def test_two_shards_each_stand_up_a_schema_of_their_own(self):
        with tempfile.TemporaryDirectory() as logs:
            done = subprocess.run([sys.executable, str(ROOT / "scripts" / "backend_shards.py"), "--shards", "2",
                                   "--tier", "quick", "--log-dir", logs, "--modules", "tests.test_json_mutation",
                                   "tests.test_reset_demo_guard"],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn("2 module(s) in 2 shard(s), tier quick", done.stdout)
            self.assertIn(": OK", done.stdout)
            schemas = set()
            for n in (1, 2):
                data = json.loads((Path(logs) / f"shard-{n}.json").read_text(encoding="utf-8"))
                self.assertGreater(data["ran"], 0)
                schemas.add(data["schema"])
        self.assertEqual(len(schemas), 2, schemas)
        self.assertNotIn(os.environ.get("PLATFORM_TEST_SCHEMA"), schemas)


class Tiers(unittest.TestCase):
    """backend/tests/tiers.py: the quick tier skips what is marked slow; unset or full runs it."""

    PROBE = ("import unittest\nfrom tests.tiers import slow\n@slow\nclass Slow(unittest.TestCase):\n"
             "    def test_it(self): pass\nclass Quick(unittest.TestCase):\n    def test_it(self): pass\n"
             "r = unittest.TextTestRunner(verbosity=0).run(unittest.defaultTestLoader.loadTestsFromModule("
             "__import__('__main__')))\nprint('skipped', len(r.skipped), 'ran', r.testsRun)\n")

    def probe(self, tier: str | None) -> str:
        env = {k: v for k, v in os.environ.items() if k != "PLATFORM_TESTS_TIER"}
        if tier:
            env["PLATFORM_TESTS_TIER"] = tier
        done = subprocess.run([sys.executable, "-c", self.PROBE], cwd=ROOT / "backend", env=env, capture_output=True,
                              text=True, timeout=300)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip().splitlines()[-1]

    def test_quick_skips_slow_tests_and_full_or_unset_runs_them(self):
        self.assertEqual(self.probe("quick"), "skipped 1 ran 2")
        self.assertEqual(self.probe("full"), "skipped 0 ran 2")
        self.assertEqual(self.probe(None), "skipped 0 ran 2")


@unittest.skipUnless(sys.platform == "win32", "the step programs are checked in Windows PowerShell")
class StepPrograms(unittest.TestCase):
    """scripts/step-programs.ps1: built and current for the checkout, as bootstrap stage 6 decides; run-suites.ps1
    runs no backend test when one is not, and says which and how to build them."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        steps = self.root / "steps" / "step-003-fingerprinting"
        (steps / "src" / "Fingerprinting.Cli").mkdir(parents=True)
        (steps / "src" / "Fingerprinting.Cli" / "Program.cs").write_text("class P {}\n")
        (steps / "schemas").mkdir()
        (steps / "global.json").write_text("{}\n")
        self.steps = steps

    def powershell(self, script: str) -> subprocess.CompletedProcess:
        prelude = f". '{ROOT / 'scripts' / 'step-programs.ps1'}'; $root = '{self.root}'; "
        return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", prelude + script],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")

    def stale(self) -> list[str]:
        done = self.powershell("$w = Get-StepProgramsWant -Root $root -Sdk '10.0.100' -NugetSources ''; "
                               "Get-StaleStepPrograms -Root $root -Want $w | ForEach-Object { $_.Program + '|' + $_.Why }")
        self.assertEqual(done.returncode, 0, done.stderr)
        return [line for line in done.stdout.splitlines() if line.strip()]

    def publish_all(self):
        """As bootstrap stage 6 leaves them: each executable, and its stamp of the current sources."""
        done = self.powershell("$w = Get-StepProgramsWant -Root $root -Sdk '10.0.100' -NugetSources ''; "
                               "foreach ($p in $StepPrograms) { $d = Join-Path (Join-Path $root $StepProgramsFolder) $p[1]; "
                               "New-Item -ItemType Directory -Force $d | Out-Null; Set-Content (Join-Path $d $p[2]) 'exe'; "
                               "Set-Content (Get-StepProgramStamp $root $p) $w -Encoding ascii }")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_missing_then_current_then_out_of_date(self):
        missing = self.stale()
        self.assertEqual(len(missing), 7, missing)
        self.assertIn("Fingerprinting.Cli|not built: publish\\Fingerprinting.Cli.exe does not exist", missing)
        self.publish_all()
        self.assertEqual(self.stale(), [])
        (self.steps / "src" / "Fingerprinting.Cli" / "Program.cs").write_text("class P { int x; }\n")
        changed = self.stale()
        self.assertEqual(len(changed), 7, changed)
        self.assertTrue(all("out of date" in line for line in changed), changed)

    def test_run_suites_runs_no_backend_test_on_stale_programs_and_says_how_to_build_them(self):
        (self.root / "scripts").mkdir()
        for name in ("run-suites.ps1", "step-programs.ps1", "select_suites.py", "backend_shards.py"):
            shutil.copy2(ROOT / "scripts" / name, self.root / "scripts" / name)
        # A Python for the copy's selection (standard library only): the virtual environment's launcher and its config.
        venv = self.root / "backend" / ".venv"
        (venv / "Scripts").mkdir(parents=True)
        shutil.copy2(Path(sys.prefix) / "pyvenv.cfg", venv / "pyvenv.cfg")
        shutil.copy2(Path(sys.prefix) / "Scripts" / "python.exe", venv / "Scripts" / "python.exe")
        (self.root / "backend" / "tests").mkdir()
        (self.root / "backend" / "tests" / "test_example.py").write_text("")
        done = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                               str(self.root / "scripts" / "run-suites.ps1"), "-Paths", "backend/tests/test_example.py"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=self.root)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("The backend tests need the C# step programs built and current for this checkout; 7 are not:",
                      done.stdout)
        self.assertIn("  Fingerprinting.Cli: not built", done.stdout)
        self.assertIn("Build them, then run the suites again: .\\scripts\\bootstrap.ps1 -Stage 6", done.stdout)
        self.assertNotIn("started:", done.stdout)
