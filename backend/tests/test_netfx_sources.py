""".NET Framework sources in conversion preparation (34-CONVERSION-ARCHITECTURE Part E; 36-COPILOT-ENHANCED-CONVERSION
"Old-style projects").

- app.conversion.frameworks knows a .NET Framework target in both spellings, v4.7 / v4.7.2 (an old-style project's
  TargetFrameworkVersion) and net47 / net472 / net48 (an SDK-style one's), and which dependency groups it consumes:
  NuGet's rules. A framework the rules do not cover is not known, never an error that stops a preparation.
- A repository whose in-scope projects are all on one .NET Framework version gets its package moves and couplings, for
  both engines (one model).
- An old-style project gets no package step, and the reason says plainly that the engine retargets it.
- End to end: the preparation of such a repository, with a recommended package that carries dependency groups, prepares
  the conversion, both engines' inputs included (the repository's engine is Claude Code: its .claude folder is there).

Runs in this test run's own schema (tests/__init__.py). Run from backend/:  python -m unittest tests.test_netfx_sources -v
"""
import datetime
import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from sqlalchemy import text

from app import models
from app.conversion import frameworks, gitops, msbuild, planner
from app.db import SessionLocal
from app.engine import convert
from app.engine.inputs import collect
from app.steps import conversion_preparation
from tests.support import TEST_ENGAGEMENT_ID, CommittedTestEngagement

GROUPS = ["net45", "net462", "net48", "netstandard2.0", "netstandard1.3", "net6.0", "net8.0-windows", "any"]


class Rules(unittest.TestCase):
    def test_both_spellings_are_dotnet_framework_and_never_confused_with_dotnet_5_and_later(self):
        for tfm, version in (("v4.7", (4, 7, 0)), ("v4.7.2", (4, 7, 2)), ("net472", (4, 7, 2)), ("net48", (4, 8, 0)),
                             ("V4.8", (4, 8, 0)), ("net403", (4, 0, 3))):
            self.assertEqual(frameworks._parse(tfm), ("netfx", version), tfm)
        self.assertEqual(frameworks._parse("net5.0"), ("netcore", (5, 0)))
        self.assertEqual(frameworks._parse("net10.0"), ("netcore", (10, 0)))
        self.assertEqual(frameworks._parse("net8.0-windows"), ("platform", None))
        self.assertTrue(frameworks.is_netfx("v4.8") and not frameworks.is_netfx("net8.0"))

    def test_compatible_groups_follow_nuget(self):
        expected = {
            "v4.7":   {"net45": True, "net462": True, "net48": False, "netstandard2.0": True, "netstandard1.3": True},
            "v4.7.2": {"net45": True, "net462": True, "net48": False, "netstandard2.0": True, "netstandard1.3": True},
            "net472": {"net45": True, "net462": True, "net48": False, "netstandard2.0": True, "netstandard1.3": True},
            "net48":  {"net45": True, "net462": True, "net48": True, "netstandard2.0": True, "netstandard1.3": True},
        }
        for target, groups in expected.items():
            got = {g: frameworks.compatible(target, g) for g in GROUPS}
            self.assertEqual(got, {**groups, "net6.0": False, "net8.0-windows": False, "any": True}, target)
        # NuGet's table: netstandard2.0 from net461, 1.3 from net46, 1.0 from net45, 2.1 never.
        self.assertFalse(frameworks.compatible("v4.6", "netstandard2.0"))
        self.assertTrue(frameworks.compatible("v4.6", "netstandard1.3"))
        self.assertFalse(frameworks.compatible("v4.5", "netstandard1.3"))
        self.assertFalse(frameworks.compatible("net48", "netstandard2.1"))
        # .NET 5+ targets as before.
        self.assertTrue(frameworks.compatible("net10.0", "netstandard2.0"))
        self.assertFalse(frameworks.compatible("net10.0", "net472"))

    def test_an_unknown_target_says_which_framework(self):
        with self.assertRaises(frameworks.UnknownFramework) as raised:
            frameworks.compatible("portable-net45+win8", "net45")
        self.assertIn("portable-net45+win8", str(raised.exception))

    def test_supports_and_dependency_minimums_on_a_dotnet_framework_source(self):
        meta = {"dependencyFrameworks": ["net45", "netstandard2.0", "net6.0"], "libFrameworks": None,
                "dependencies": [
                    {"framework": "net45", "packages": [{"id": "Acme.Core", "range": "[1.0.0, )"}]},
                    {"framework": "netstandard2.0", "packages": [{"id": "Acme.Core", "range": "[2.0.0, )"}]},
                    {"framework": "net6.0", "packages": [{"id": "Acme.Core", "range": "[3.0.0, )"}]}]}
        for target in ("v4.7", "v4.7.2", "net472", "net48"):
            self.assertTrue(frameworks.supports(meta, target).supported, target)
            # The nearest group: .NET Framework before .NET Standard.
            self.assertEqual(frameworks.dependency_minimums(meta, target), {"acme.core": (1, 0, 0)}, target)
        self.assertEqual(frameworks.dependency_minimums(meta, "net10.0"), {"acme.core": (3, 0, 0)})
        only_core = {"dependencyFrameworks": ["net6.0"], "libFrameworks": ["net6.0"],
                     "dependencies": [{"framework": "net6.0", "packages": []}]}
        self.assertFalse(frameworks.supports(only_core, "v4.7").supported)
        self.assertEqual(frameworks.dependency_minimums(only_core, "v4.7"), {})

    def test_frameworks_deltas_still_never_apply_to_a_dotnet_framework_source(self):
        self.assertFalse(planner._crosses("v4.7", "net10.0", "net10.0"))
        self.assertFalse(planner._crosses("net472", "net10.0", "net10.0"))
        self.assertTrue(planner._crosses("net8.0", "net10.0", "net10.0"))


OLD_STYLE = """<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
    <OutputType>Library</OutputType>
    <TargetFrameworkVersion>{tfm}</TargetFrameworkVersion>
  </PropertyGroup>
</Project>
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@client-a.example", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


class NetfxRepository(unittest.TestCase):
    """A repository of old-style projects, every one in scope on `TFM`, and one recommended package whose versions
    carry dependency groups (the shape that failed: one framework left after descoping)."""
    TFM = "v4.7"

    def setUp(self):
        self.db = SessionLocal()
        self.engagement = CommittedTestEngagement(self.db)
        self.tmp = Path(tempfile.mkdtemp(prefix="netfx-"))
        self.repo = None
        # Cleanups run even when setUp fails part way: never a transaction left open for the next test to wait on.
        self.addCleanup(self.remove)
        tag = uuid.uuid4().hex[:6]
        self.slug = f"ledger-{tag}"
        root = self.tmp / "ledger"
        for name in ("Ledger.Core", "Ledger.Web"):
            (root / name).mkdir(parents=True)
            (root / name / f"{name}.csproj").write_text(OLD_STYLE.format(tfm=self.TFM), encoding="utf-8")
            (root / name / "packages.config").write_text('<packages><package id="Acme.Json" version="12.0.1" /></packages>\n',
                                                         encoding="utf-8")
        _git(root, "init", "-q", "-b", "main")
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "legacy")
        self.repo = models.Repository(engagement_id=TEST_ENGAGEMENT_ID, name=f"Ledger {tag}", slug=self.slug,
                                      source_type="local_path", local_path=str(root), local_path_normalised=str(root).lower(),
                                      root_folder_name="ledger", ingest_status="scanned", conversion_engine="claude-code",
                                      ingest_commit_sha=_git(root, "rev-parse", "HEAD"))
        self.db.add(self.repo)
        self.db.flush()
        for name in ("Ledger.Core", "Ledger.Web"):
            project = models.Project(repository_id=self.repo.id, name=name, relative_path=f"{name}/{name}.csproj",
                                     extension=".csproj", structural_type="class_library", project_format="legacy_msbuild",
                                     language="csharp", package_management_style="packages_config", parse_status="success",
                                     target_framework_raw=self.TFM)
            self.db.add(project)
            self.db.flush()
            self.db.add(models.PackageAssessment(id=f"{tag}-{name}", repository_id=self.repo.id, project_id=project.id,
                                                 package_id="Acme.Json", current_version="12.0.1",
                                                 recommended_version="13.0.3", outcome="upgrade_safe", confidence=1))
        self.package_id = "Acme.Json"
        self.feed = f"https://feed.client-a.example/{tag}"
        groups = [{"framework": "net45", "packages": [{"id": "Acme.Core", "range": "[1.0.0, )"}]},
                  {"framework": "netstandard2.0", "packages": [{"id": "Acme.Core", "range": "[2.0.0, )"}]},
                  {"framework": "net6.0", "packages": [{"id": "Acme.Core", "range": "[3.0.0, )"}]}]
        meta = {"dependencyFrameworks": ["net45", "net6.0", "netstandard2.0"], "libFrameworks": None, "dependencies": groups}
        self.db.add(models.PackageLookupCache(feed_url_normalised=self.feed, package_id=self.package_id,
                                              versions=["12.0.1", "13.0.3"], metadata_={"12.0.1": meta, "13.0.3": meta},
                                              fetched_at=datetime.datetime.now(datetime.timezone.utc)))
        self.db.commit()

    def remove(self):
        self.db.rollback()
        if self.repo is None or self.repo.id is None:
            self.db.close()
            shutil.rmtree(self.tmp, ignore_errors=True)
            return
        self.db.execute(text("delete from package_lookup_cache where feed_url_normalised = :f"), {"f": getattr(self, "feed", "")})
        self.db.execute(text("delete from package_assessments where repository_id = :r"), {"r": self.repo.id})
        self.db.execute(text("delete from conversion_results where repository_id = :r"), {"r": self.repo.id})
        self.db.execute(text("delete from projects where repository_id = :r"), {"r": self.repo.id})
        self.db.commit()
        root = Path(self.repo.local_path)
        for line in _git(root, "worktree", "list", "--porcelain").splitlines():
            if line.startswith("worktree ") and Path(line[9:]).resolve() != root.resolve():
                _git(root, "worktree", "remove", "--force", line[9:])
        self.db.execute(text("delete from conversion_plans where repository_id = :r"), {"r": self.repo.id})
        self.db.execute(text("delete from repositories where id = :r"), {"r": self.repo.id})
        self.db.commit()
        shutil.rmtree(convert.conversions_dir(TEST_ENGAGEMENT_ID, self.slug).parent, ignore_errors=True)
        self.engagement.remove()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_package_moves_from_a_dotnet_framework_source_compute_their_couplings(self):
        packages, moves, _ = planner.package_moves(self.db, self.repo.id, self.TFM, "net10.0", [])
        [p] = packages.values()
        self.assertTrue(p["dependencies_known"])
        self.assertTrue(p["support"]["current"][self.TFM]["supported"])
        self.assertEqual(moves[0].before, {"acme.core": (3, 0, 0)})      # merged over both frameworks: the higher
        planner.couplings(moves)

    def test_the_model_reports_packages_for_a_dotnet_framework_source(self):
        model = collect.collect(self.db, self.repo)
        self.assertEqual(model["current_frameworks"], [self.TFM])
        [package] = model["packages"]
        self.assertEqual((package["package"], package["dependencies_known"]), ("Acme.Json", True))

    def test_a_framework_the_rules_do_not_cover_is_not_known_and_stops_nothing(self):
        packages, _, _ = planner.package_moves(self.db, self.repo.id, "portable-net45+win8", "net10.0", [])
        [p] = packages.values()
        self.assertFalse(p["dependencies_known"])
        support = p["support"]["current"]["portable-net45+win8"]
        self.assertIsNone(support["supported"])
        self.assertIn("Ledger.Core/Ledger.Core.csproj", support["basis"])
        self.assertIn("portable-net45+win8", support["basis"])

    def test_an_old_style_project_gets_no_package_step_and_the_reason_says_the_engine_retargets_it(self):
        with self.assertRaises(msbuild.OldStyleProject) as raised:
            msbuild.framework_declarations(Path(self.repo.local_path), [
                {"relative_path": "Ledger.Core/Ledger.Core.csproj", "target_framework_raw": self.TFM,
                 "target_framework_source": "project"}])
        self.assertEqual(str(raised.exception),
                         f"Ledger.Core/Ledger.Core.csproj is an old-style project (TargetFrameworkVersion {self.TFM}): "
                         "old-style projects are retargeted by the conversion engine, not the package step")

    def test_preparation_prepares_it_for_both_engines(self):
        result = self.prepare()
        attempt = json.loads((convert.conversions_dir(TEST_ENGAGEMENT_ID, self.slug) / conversion_preparation.LAST_PREPARE)
                             .read_text(encoding="utf-8"))
        self.assertEqual(result.exit_status, "COMPLETED")
        self.assertEqual(attempt["status"], "prepared", attempt.get("message"))
        # No package step here (no discovery inventory): the package changes go to the engine as instructions.
        self.assertIn("package step skipped: no package step: ", attempt["message"])
        worktree = Path(convert.records(TEST_ENGAGEMENT_ID, self.slug)[-1]["worktree"])
        self.assertTrue((worktree / ".claude").is_dir())
        self.assertTrue((worktree / ".github" / "copilot-instructions.md").is_file())

    def prepare(self):
        from app.config import settings

        return conversion_preparation.run(_context(self.repo.id, settings.database_url))


def _context(repository_id, database_url: str):
    return type("Context", (), {"parameters": {"repository_id": str(repository_id)}, "database_url": database_url,
                                "job_execution_id": str(uuid.uuid4())})()


class NetfxV48Repository(NetfxRepository):
    """The second repository's shape: v4.8 only in scope."""
    TFM = "v4.8"


if __name__ == "__main__":
    unittest.main()
