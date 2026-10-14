"""Conversion — 34-CONVERSION-ARCHITECTURE.md C1, C4, E, F: framework support,
where versions and frameworks are declared, the deterministic approaches,
which packages move together or in order, the ordering around a retarget,
and the unit loop with its failure policy by dependency.

The unit loop runs on a throwaway git repository with build and test
replaced by fakes (a build fails when a marker package is declared), inside
one rolled-back transaction. The real proof is eShopOnWeb, run by
`python -m app.conversion.runner`.

Run from backend/:  python -m unittest tests.test_conversion -v
"""

import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from app import models
from app.conversion import approaches, dotnet, frameworks, gitops, msbuild, planner, runner
from tests.support import TEST_ENGAGEMENT_ID
from tests.test_item_catalog import ItemCatalogTestCase

PROPS = """<Project>
  <PropertyGroup>
    <ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally>
    <TargetFramework>net8.0</TargetFramework>
    <AspNetVersion>8.0.2</AspNetVersion>
  </PropertyGroup>
  <ItemGroup>
    <PackageVersion Include="Good.A" Version="1.0.0" />
    <PackageVersion Include="Bad.Package" Version="1.0.0" />
    <PackageVersion Include="Good.B" Version="1.0.0" />
    <PackageVersion Include="Asp.One" Version="$(AspNetVersion)" />
    <PackageVersion Include="Asp.Two" Version="$(AspNetVersion)" />
  </ItemGroup>
</Project>
"""
CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <ItemGroup>
    <PackageReference Include="Good.A" />
    <PackageReference Include="Bad.Package" />
    <PackageReference Include="Good.B" />
    <PackageReference Include="Asp.One" />
    <PackageReference Include="Over.Ride" VersionOverride="3.0.0" />
  </ItemGroup>
</Project>
"""


def _repo(root: Path) -> None:
    (root / "src" / "App").mkdir(parents=True)
    (root / "Directory.Packages.props").write_bytes(PROPS.replace("\n", "\r\n").encode())
    (root / "src" / "App" / "App.csproj").write_text(CSPROJ, encoding="utf-8")
    (root / "global.json").write_text('{\n  "sdk": {\n    "version": "8.0.x",\n    "rollForward": "latestFeature"\n  }\n}\n', encoding="utf-8")
    (root / ".gitignore").write_text("bin/\nobj/\n", encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], [*gitops.PLATFORM_IDENTITY, "commit", "-q", "-m", "legacy"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class FrameworkTests(unittest.TestCase):
    def test_compatibility(self):
        self.assertTrue(frameworks.compatible("net8.0", "netstandard2.0"))
        self.assertTrue(frameworks.compatible("net10.0", "net8.0"))
        self.assertFalse(frameworks.compatible("net8.0", "net10.0"))
        self.assertFalse(frameworks.compatible("net8.0", "net472"))
        self.assertFalse(frameworks.compatible("net8.0", "net8.0-windows7.0"))
        self.assertTrue(frameworks.compatible("net8.0", "netcoreapp3.1"))

    def test_support_follows_dependency_assessment(self):
        self.assertTrue(frameworks.supports({"dependencyFrameworks": ["net10.0"], "libFrameworks": None}, "net10.0").supported)
        self.assertFalse(frameworks.supports({"dependencyFrameworks": ["net10.0"], "libFrameworks": ["net10.0"]}, "net8.0").supported)
        self.assertTrue(frameworks.supports({"dependencyFrameworks": [], "libFrameworks": None}, "net8.0").supported)
        # An MSBuild-targets package: a net472 group, lib/ref never examined — not known.
        self.assertIsNone(frameworks.supports({"dependencyFrameworks": ["net472"], "libFrameworks": None}, "net8.0").supported)
        self.assertTrue(frameworks.supports({"dependencyFrameworks": ["net472"], "libFrameworks": []}, "net8.0").supported)


class DeclarationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="conversion-decl-"))
        _repo(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_framework_declared_in_props(self):
        projects = [{"relative_path": "src/App/App.csproj", "target_framework_raw": "net8.0",
                     "target_framework_source": "Directory.Packages.props"}]
        [d] = msbuild.framework_declarations(self.root, projects)
        self.assertEqual(("Directory.Packages.props", "TargetFramework", "net8.0", ["src/App/App.csproj"]),
                         (d.file, d.element, d.value, d.projects))

    def test_versions_resolve_where_declared(self):
        good = msbuild.version_declaration(self.root, "src/App/App.csproj", "Good.A")
        self.assertEqual(("Directory.Packages.props", "package_version", "1.0.0"), (good.file, good.kind, good.value))
        asp = msbuild.version_declaration(self.root, "src/App/App.csproj", "Asp.One")
        self.assertEqual(("property", "AspNetVersion", "8.0.2", ["Asp.Two"]), (asp.kind, asp.name, asp.value, asp.shared_with))
        override = msbuild.version_declaration(self.root, "src/App/App.csproj", "Over.Ride")
        self.assertEqual(("src/App/App.csproj", "version_override", "3.0.0"), (override.file, override.kind, override.value))

    def test_edits_keep_line_endings(self):
        path = self.root / "Directory.Packages.props"
        original = path.read_bytes()
        asp = msbuild.version_declaration(self.root, "src/App/App.csproj", "Asp.One")
        text, changed = msbuild.set_version(msbuild.read(path), asp, "10.0.12")
        msbuild.write(path, original, text)
        self.assertTrue(changed)
        self.assertIn(b"<AspNetVersion>10.0.12</AspNetVersion>\r\n", path.read_bytes())
        self.assertEqual(original.count(b"\r\n"), path.read_bytes().count(b"\r\n"))


class ApproachTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="conversion-approach-"))
        _repo(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_retarget_edits_the_declaration_and_the_sdk_pin(self):
        approach = approaches.RetargetTfm()
        target = {"from": "net8.0", "to": "net10.0",
                  "declarations": [{"file": "Directory.Packages.props", "element": "TargetFramework", "value": "net8.0", "projects": ["a"]}]}
        self.assertEqual("apply", approach.pre_check(self.root, target).outcome)
        approach.apply(self.root, target)
        self.assertEqual([], approach.post_check(self.root, target))
        self.assertIn('"version": "10.0.100"', (self.root / "global.json").read_text(encoding="utf-8"))
        self.assertEqual("not_applicable", approach.pre_check(self.root, target).outcome)

    def test_a_shared_property_is_bumped_once_and_refused_when_recommendations_differ(self):
        approach = approaches.PackageUpgradeSafe()
        decl = {"file": "Directory.Packages.props", "kind": "property", "name": "AspNetVersion", "shared_with": ["Asp.Two"]}
        one = {"package_id": "Asp.One", "from": "8.0.2", "to": "10.0.12", "project": "src/App/App.csproj", "declaration": decl,
               "shared_recommendations": {"Asp.One": "10.0.12", "Asp.Two": "10.0.12"}}
        self.assertEqual("apply", approach.pre_check(self.root, one).outcome)
        approach.apply(self.root, one)
        self.assertEqual([], approach.post_check(self.root, one))
        # The second occurrence of the same declaration finds it done.
        self.assertEqual("not_applicable", approach.pre_check(self.root, {**one, "package_id": "Asp.One"}).outcome)
        disagreeing = {**one, "shared_recommendations": {"Asp.One": "10.0.12", "Asp.Two": "9.0.0"}}
        fresh = Path(tempfile.mkdtemp(prefix="conversion-approach-"))
        try:
            _repo(fresh)
            self.assertEqual("refused", approach.pre_check(fresh, disagreeing).outcome)
        finally:
            shutil.rmtree(fresh, ignore_errors=True)


    def test_an_atomic_unit_bumps_every_package_of_its_group_in_one_edit(self):
        approach = approaches.PackageUpgradeSafe()
        decl = lambda name: {"file": "Directory.Packages.props", "kind": "package_version", "name": name, "shared_with": []}  # noqa: E731
        target = {"bumps": [
            {"package_id": p, "from": "1.0.0", "to": "2.0.0", "project": "src/App/App.csproj", "declaration": decl(p)}
            for p in ("Good.A", "Good.B")], "group_reason": "test"}
        self.assertEqual("apply", approach.pre_check(self.root, target).outcome)
        self.assertEqual(2, len(approach.apply(self.root, target)))
        self.assertEqual([], approach.post_check(self.root, target))
        self.assertEqual("not_applicable", approach.pre_check(self.root, target).outcome)
        self.assertIn("together", approach.message(target).splitlines()[0])

    def test_the_program_delta_fix_pins_an_implicit_program_internal_and_refuses_a_public_one(self):
        approach = approaches.PinProgramInternal()
        program = self.root / "src" / "App" / "Program.cs"
        program.write_bytes("var app = WebApplication.Create(args);\r\napp.Run();\r\n".encode("utf-8-sig"))
        target = {"file": "src/App/Program.cs", "delta_id": "net10-public-top-level-program", "breaks_from": "net10.0",
                  "consumers": ["tests/T/ProgramTest.cs"]}
        self.assertEqual("apply", approach.pre_check(self.root, target).outcome)
        approach.apply(self.root, target)
        self.assertEqual([], approach.post_check(self.root, target))
        data = program.read_bytes()
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))                         # BOM kept
        self.assertIn(b"internal partial class Program { }\r\n", data)          # CRLF kept
        self.assertEqual("not_applicable", approach.pre_check(self.root, target).outcome)
        program.write_text("var x = 1;\npublic partial class Program { }\n", encoding="utf-8")
        self.assertEqual("refused", approach.pre_check(self.root, target).outcome)


class CouplingTests(unittest.TestCase):
    @staticmethod
    def move(pid, frm, to, before=None, after=None, outcome="upgrade_safe"):
        v = frameworks.parse_version
        return planner.PackageMove(pid, frm, to, outcome, {k: v(x) for k, x in (before or {}).items()},
                                   {k: v(x) for k, x in (after or {}).items()})

    def test_requiring_a_new_major_of_another_package_moves_them_together(self):
        together, depends = planner.couplings([
            self.move("Ardalis.Specification", "7.0.0", "9.3.1"),
            self.move("Ardalis.Specification.EntityFrameworkCore", "7.0.0", "9.3.1",
                      {"ardalis.specification": "7.0.0"}, {"ardalis.specification": "9.3.1"})])
        self.assertEqual([("ardalis.specification.entityframeworkcore", "ardalis.specification")], [t[:2] for t in together])
        self.assertEqual([], depends)

    def test_requiring_a_newer_minor_orders_the_dependency_first(self):
        together, depends = planner.couplings([
            self.move("Lib.Core", "1.0.0", "1.4.0"),
            self.move("Lib.Web", "2.0.0", "2.1.0", {"lib.core": "1.0.0"}, {"lib.core": "1.4.0"})])
        self.assertEqual([], together)
        self.assertEqual([("lib.web", "lib.core")], [d[:2] for d in depends])

    def test_one_family_released_together_moves_together(self):
        # AccountsApi conversion 2: MSTest.TestFramework 4.5.1 beside MSTest.TestAdapter 4.4.1 discovered no test.
        together, depends = planner.couplings([
            self.move("MSTest.TestFramework", "4.4.1", "4.5.1"),
            self.move("MSTest.TestAdapter", "4.4.1", "4.5.1", {"mstest.testframework": "4.4.1"}, {"mstest.testframework": "4.5.1"})])
        self.assertEqual([("mstest.testadapter", "mstest.testframework")], [t[:2] for t in together])
        self.assertEqual([], depends)

    def test_a_shared_dependency_one_family_raises_moves_them_together_another_family_waits(self):
        together, depends = planner.couplings([
            self.move("Azure.Identity", "1.10.4", "1.21.0", {"azure.core": "1.36.0"}, {"azure.core": "1.53.0"}),
            self.move("Azure.Extensions.Secrets", "1.3.1", "1.5.2", {"azure.core": "1.37.0"}, {"azure.core": "1.61.0"}),
            self.move("Ardalis.Specification.EntityFrameworkCore", "7.0.0", "9.3.1",
                      {"microsoft.entityframeworkcore": "6.0.6"}, {"microsoft.entityframeworkcore": "9.0.8"}),
            self.move("Microsoft.EntityFrameworkCore.SqlServer", "8.0.2", "10.0.12",
                      {"microsoft.entityframeworkcore": "8.0.2"}, {"microsoft.entityframeworkcore": "10.0.12"})])
        self.assertEqual([("azure.extensions.secrets", "azure.identity")], [t[:2] for t in together])
        self.assertEqual([("ardalis.specification.entityframeworkcore", "microsoft.entityframeworkcore.sqlserver")],
                         [d[:2] for d in depends])

    def test_framework_family_dependencies_couple_nothing(self):
        together, depends = planner.couplings([
            self.move("MediatR", "12.0.1", "14.2.0", {"microsoft.extensions.logging": "6.0.0"}, {"microsoft.extensions.logging": "10.0.0"}),
            self.move("FluentValidation", "11.9.0", "12.2.0", {"microsoft.extensions.logging": "8.0.0"}, {"microsoft.extensions.logging": "10.0.12"})])
        self.assertEqual(([], []), (together, depends))


class PlacementTests(unittest.TestCase):
    @staticmethod
    def group(cur_to, rec_from):
        return {"support": {"P": {"from": "1", "to": "2",
                                  "current": {"net8.0": {"supported": True}, "net10.0": {"supported": cur_to}},
                                  "recommended": {"net8.0": {"supported": rec_from}, "net10.0": {"supported": True}}}}}

    def test_ordering_around_the_retarget(self):
        self.assertEqual("after", planner._place(self.group(True, False), "net8.0", "net10.0")[0])     # drops net8.0
        self.assertEqual("before", planner._place(self.group(False, True), "net8.0", "net10.0")[0])    # current lacks net10.0
        self.assertEqual("before", planner._place(self.group(None, True), "net8.0", "net10.0")[0])     # not known: move to known
        self.assertEqual("before", planner._place(self.group(True, True), "net8.0", "net10.0")[0])     # free: first
        self.assertEqual("after", planner._place(self.group(True, None), "net8.0", "net10.0")[0])      # no data
        place, reason = planner._place(self.group(False, False), "net8.0", "net10.0")
        self.assertEqual("after", place)
        self.assertIn("no order builds", reason)


BAD_BUILDS = True   # the fake build refuses Bad.Package 2.0.0 while this is set


def fake_build(worktree, solution, timeout=0):
    bad = BAD_BUILDS and '"Bad.Package" Version="2.0.0"' in (Path(worktree) / "Directory.Packages.props").read_text(encoding="utf-8")
    return dotnet.Run(not bad, 1 if bad else 0, "error NU1605: fake" if bad else "Build succeeded.")


def fake_test(worktree, project, trx, timeout=0, count=3):
    trx.parent.mkdir(parents=True, exist_ok=True)
    results = "".join(f'<UnitTestResult testName="T{i}" outcome="Passed" />' for i in range(count))
    trx.write_text(f'<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010"><Results>{results}</Results></TestRun>',
                   encoding="utf-8")
    return dotnet.Run(True, 0, "Passed!"), dotnet.read_trx(trx)


class UnitLoopTests(ItemCatalogTestCase):
    def setUp(self):
        super().setUp()
        self.work = Path(tempfile.mkdtemp(prefix="conversion-loop-"))
        self.root = self.work / "repo"
        self.root.mkdir()
        _repo(self.root)
        tag = uuid.uuid4().hex[:8]
        self.repository = models.Repository(
            engagement_id=TEST_ENGAGEMENT_ID, name=f"t-{tag}", root_folder_name=f"t-{tag}", slug=f"t-{tag}",
            local_path=str(self.root), local_path_normalised=str(self.root).lower(), source_type="local_path", ingest_status="scanned")
        self.db.add(self.repository)
        from app.conversion import recipes
        recipes.sync(self.db)
        self.plan = models.ConversionPlan(
            id=uuid.uuid4(), repository_id=self.repository.id, engagement_id=TEST_ENGAGEMENT_ID,
            legacy_commit=gitops.head(self.root), target_layout="in_place", target_framework="net10.0",
            recipes=[], branch=f"conversion/{tag}", worktree_path=str(self.work / "plan" / "target"),
            ordering={"solution": "App.sln", "unit_test_projects": ["tests/Unit/Unit.csproj"]})
        self.db.add(self.plan)
        self.db.flush()
        # 1 Good.A; 2 Bad.Package (fails to build); 3 Asp.One, which depends on 2;
        # 4 Good.B, independent; 5 an assisted unit; 6 depends on the assisted one.
        units = [("Good.A", [], "deterministic"), ("Bad.Package", [], "deterministic"), ("Asp.One", [2], "deterministic"),
                 ("Good.B", [], "deterministic"), ("Over.Ride", [], "assisted"), ("Good.A", [5], "deterministic")]
        for sequence, (package, needs, automation) in enumerate(units, start=1):
            frm, to = ("8.0.2", "10.0.12") if package == "Asp.One" else ("3.0.0", "4.0.0") if package == "Over.Ride" else ("1.0.0", "2.0.0")
            kind, name = ("property", "AspNetVersion") if package == "Asp.One" else ("package_version", package)
            self.db.add(models.ConversionUnit(
                unit_id=f"{self.plan.id}:{sequence}", plan_id=self.plan.id, recipe_id="package-upgrade-safe-bump", step_id="F01",
                approach_id="package-upgrade-safe", approach_version="0.2.0", sequence=sequence, order_reason="test",
                automation_class=automation, depends_on=[{"sequence": n, "reason": "test"} for n in needs],
                target={"package_id": package, "from": frm, "to": to, "project": "src/App/App.csproj",
                        "declaration": {"file": "Directory.Packages.props", "kind": kind, "name": name, "shared_with": []}}))
        self.db.flush()

    def tearDown(self):
        subprocess.run(["git", "-C", str(self.root), "worktree", "prune"], capture_output=True)
        shutil.rmtree(self.work, ignore_errors=True)
        super().tearDown()

    def run_plan(self, count=3):
        with mock.patch.object(dotnet, "build", fake_build), \
             mock.patch.object(dotnet, "test", lambda w, p, t, timeout=0: fake_test(w, p, t, count=count)), \
             mock.patch.object(dotnet, "shutdown_build_servers", lambda: None):
            runner.Run(self.db, self.plan).run()

    def units(self):
        return {u.sequence: u for u in self.db.query(models.ConversionUnit).filter_by(plan_id=self.plan.id)}

    def test_a_failure_blocks_only_its_dependents_and_a_rerun_retries_them(self):
        before = runner.fingerprint(self.root)
        self.run_plan()
        units = self.units()
        self.assertTrue(self.plan.baseline["passed"])
        self.assertEqual(3, self.plan.baseline["total"])
        self.assertEqual(["committed", "failed", "blocked", "committed", "planned", "blocked"],
                         [units[n].status for n in range(1, 7)])
        self.assertIn("build", units[2].status_reason)
        self.assertEqual("waits on unit 2 (failed)", units[3].status_reason)
        self.assertIn("T1b", units[5].status_reason)                         # assisted: never applied here
        self.assertEqual("waits on unit 5 (assisted, left for T1b)", units[6].status_reason)
        self.assertEqual("partial", self.plan.status)                         # not stopped: unit 4 ran after the failure
        target = Path(self.plan.worktree_path)
        self.assertEqual(units[4].commit_sha, gitops.head(target))           # nothing red reached the branch
        self.assertFalse((self.work / "plan" / "scratch" / "002").exists())   # the red worktree was discarded
        plan_dir = target.parent
        self.assertTrue(all(runner.evidence.verify(e, plan_dir) for e in units[1].evidence))
        self.assertEqual({"diff", "build_log", "test_log", "test_results", "result"}, {e["kind"] for e in units[1].evidence})
        self.assertEqual({"diff", "build_log"}, {e["kind"] for e in units[2].evidence})   # the failure keeps its evidence

        # Bad.Package becomes buildable (here: the fake build stops refusing it); the
        # rerun retries the failed unit and its blocked dependent, committed units untouched.
        first = units[1].commit_sha
        global BAD_BUILDS
        BAD_BUILDS = False
        try:
            self.run_plan()
        finally:
            BAD_BUILDS = True
        units = self.units()
        self.assertEqual(["committed", "committed", "committed", "committed", "planned", "blocked"],
                         [units[n].status for n in range(1, 7)])
        self.assertEqual(first, units[1].commit_sha)
        self.assertEqual("partial", self.plan.status)                         # the assisted unit still waits
        log = gitops.git(target, "log", "--format=%s", f"{self.plan.legacy_commit}..HEAD").splitlines()
        self.assertEqual(["Bump Asp.One 8.0.2 -> 10.0.12", "Bump Bad.Package 1.0.0 -> 2.0.0", "Bump Good.B 1.0.0 -> 2.0.0",
                          "Bump Good.A 1.0.0 -> 2.0.0"], log)
        self.assertEqual(before, runner.fingerprint(self.root))              # the checkout was never touched

    def test_the_conversion_section_shows_units_tests_before_and_after_and_serves_only_intact_evidence(self):
        from fastapi import HTTPException

        from app.routers import conversion as api
        self.run_plan()
        view = api.get_repository_conversion(self.repository.id, None, self.db)
        self.assertEqual(("partial", "net8.0"), (view.plan.status, view.plan.tip_framework or "net8.0"))
        self.assertEqual({"committed": 2, "failed": 1, "blocked": 2, "planned": 1}, view.counts)
        self.assertEqual((3, 3), (view.baseline.total, view.baseline.passed))
        self.assertEqual((4, 3), (view.latest.sequence, view.latest.passed))      # after: the last committed unit
        failed = view.units[1]
        self.assertEqual(("failed", None), (failed.status, failed.commit_sha))
        self.assertIn("build", failed.status_reason)
        self.assertEqual([2], [d.sequence for d in view.units[2].depends_on])

        link = next(e for e in failed.evidence if e.kind == "build_log")
        response = api.get_conversion_evidence(self.plan.id, link.path, self.db)
        self.assertEqual(Path(response.path).name, "build.log")
        with self.assertRaises(HTTPException) as refused:
            api.get_conversion_evidence(self.plan.id, "../../repo/global.json", self.db)
        self.assertEqual(404, refused.exception.status_code)
        (Path(self.plan.worktree_path).parent / link.path).write_text("tampered", encoding="utf-8")
        with self.assertRaises(HTTPException) as changed:
            api.get_conversion_evidence(self.plan.id, link.path, self.db)
        self.assertEqual(409, changed.exception.status_code)

    def test_the_runner_has_no_way_to_exclude_a_unit(self):
        self.assertFalse(hasattr(runner, "exclude"))
        with mock.patch("sys.argv", ["runner", "--plan", str(self.plan.id), "--exclude", "2"]), self.assertRaises(SystemExit):
            runner.main()

    def test_a_baseline_of_zero_tests_fails_and_nothing_runs(self):
        self.run_plan(count=0)
        self.assertFalse(self.plan.baseline["passed"])
        self.assertEqual("stopped", self.plan.status)
        self.assertTrue(all(u.status == "planned" for u in self.units().values()))


if __name__ == "__main__":
    unittest.main()
