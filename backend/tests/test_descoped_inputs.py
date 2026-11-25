"""A descoped, old-style repository's conversion inputs (the hand-off's related issues 2, 3 and 4), the same for both
engines (36-COPILOT-ENHANCED-CONVERSION "Assembly references no package declares", "Changes without an instruction",
"Conversion scope"); and a conversion verified with no test project in its solution.

- Issue 3, scope: the addendum's Windows-only, deploy parameter and SOAP sections list only in-scope configuration
  files; an entry whose bindings and call sites are all outside the scope is dropped; a work item's Files never name a
  file in a restored package folder (packages/<id>.<version>/).
- Issue 4, a decided change without guidance: never "leave unchanged"; the engine is told not to make it, a person
  supplies the instruction, and preparation's warning names it (last-prepare.json and the Conversion tab).
- Issue 2, assembly references no package declares: each with its verdict (a packages folder HintPath is that package,
  looked up as one; a Windows-only assembly needs a replacement; anything else is unknown); an out-of-scope project's
  are not listed; each in-scope project's format and packages.config use are stated; a Windows-only reference raises
  windows-only-assembly-reference, which preparation names as undecided until a person records a decision.
- A conversion whose solution has no test project is still verified: every other check runs and is reported, the
  verdict is at most PARTLY PROVEN, and the missing tests are its first reason.
- Discovery never detects an item in a restored package folder, only in the repository's own files (a real scan).

Runs in this test run's own schema (tests/__init__.py). Run from backend/:  python -m unittest tests.test_descoped_inputs -v
"""
import datetime
import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from sqlalchemy import text

from app import models
from app.config import settings
from app.db import SessionLocal
from app.engine import convert, engines
from app.engine.inputs import claude, collect, render
from app.steps import conversion_preparation, item_detection
from tests.support import TEST_ENGAGEMENT_ID, CommittedTestEngagement

OLD_STYLE = """<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
    <OutputType>Library</OutputType>
    <TargetFrameworkVersion>v4.7</TargetFrameworkVersion>
  </PropertyGroup>
{references}
</Project>
"""
JOBS_REFERENCES = """  <ItemGroup>
    <Reference Include="Microsoft.SqlServer.ManagedDTS, Version=13.0.0.0"><HintPath>..\\Dependencies\\Microsoft.SqlServer.ManagedDTS.dll</HintPath></Reference>
    <Reference Include="Microsoft.Practices.EnterpriseLibrary.Common, Version=6.0.0.0"><HintPath>..\\packages\\EnterpriseLibrary.Common.6.0.1304.0\\lib\\NET45\\Microsoft.Practices.EnterpriseLibrary.Common.dll</HintPath></Reference>
    <Reference Include="Acme.Vendor"><HintPath>..\\Dependencies\\Acme.Vendor.dll</HintPath></Reference>
    <Reference Include="Sybase.AdoNet4.AseClient" />
  </ItemGroup>"""

FILES = {
    "Jobs/Jobs.csproj": OLD_STYLE.format(references=JOBS_REFERENCES),
    "Jobs/Clock.cs": "class Clock { System.DateTime Now() => System.DateTime.Now; }\n",
    "Jobs/app.config": "<configuration />\n",
    "Archive/Archive.csproj": OLD_STYLE.format(references='  <ItemGroup><Reference Include="Archive.Vendor">'
                                                          '<HintPath>..\\Dependencies\\Archive.Vendor.dll</HintPath>'
                                                          '</Reference></ItemGroup>'),
    "Archive/app.config": "<configuration />\n",
    "Dependencies/Microsoft.SqlServer.ManagedDTS.dll": "not a real assembly\n",
    "Dependencies/Acme.Vendor.dll": "not a real assembly\n",
    "Dependencies/Archive.Vendor.dll": "not a real assembly\n",
    "packages/EnterpriseLibrary.Common.6.0.1304.0/lib/NET45/Microsoft.Practices.EnterpriseLibrary.Common.dll": "dll\n",
    "packages/Some.Tool.1.2.3/tools/install.ps1": "Write-Host 'a package's own script'\n",
    "build/build.ps1": "dotnet build\n",
}
JOBS, ARCHIVE = "Jobs/Jobs.csproj", "Archive/Archive.csproj"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@client-a.example", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _context(repository_id):
    return type("Context", (), {"parameters": {"repository_id": str(repository_id)}, "database_url": settings.database_url,
                                "job_execution_id": str(uuid.uuid4())})()


class DescopedRepository(unittest.TestCase):
    """Two old-style projects, Archive left out of scope; Jobs references the SSIS runtime and a Sybase client (Windows
    only), an undeclared Enterprise Library package by its packages folder, and a vendor DLL; outbound bindings in both
    projects' configuration files; Encoding.Default decided on explicit UTF-8 (no guidance yet: on the allow-list),
    DateTime.Now (guidance), and the Windows-only item."""

    def setUp(self):
        self.db = SessionLocal()
        self.engagement = CommittedTestEngagement(self.db)
        self.tmp = Path(tempfile.mkdtemp(prefix="descoped-"))
        self.repo = None
        self.addCleanup(self.remove)
        tag = uuid.uuid4().hex[:6]
        self.tag, self.slug = tag, f"descoped-{tag}"
        root = self.tmp / "descoped"
        for rel, body in FILES.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(body, encoding="utf-8")
        _git(root, "init", "-q", "-b", "main")
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "legacy")
        self.repo = models.Repository(engagement_id=TEST_ENGAGEMENT_ID, name=f"Descoped {tag}", slug=self.slug,
                                      source_type="local_path", local_path=str(root), local_path_normalised=str(root).lower(),
                                      root_folder_name="descoped", ingest_status="scanned",
                                      ingest_commit_sha=_git(root, "rev-parse", "HEAD"))
        self.db.add(self.repo)
        self.db.flush()
        self.projects = {}
        for rel in (JOBS, ARCHIVE):
            project = models.Project(repository_id=self.repo.id, name=Path(rel).stem, relative_path=rel, extension=".csproj",
                                     structural_type="class_library", project_format="legacy_msbuild", language="csharp",
                                     package_management_style="none", parse_status="success", target_framework_raw="v4.7")
            self.db.add(project)
            self.db.flush()
            self.projects[rel] = project
        self.db.add(models.ConversionScope(repository_id=self.repo.id, excluded_projects=[ARCHIVE],
                                           known_projects=[ARCHIVE, JOBS], saved_by_name="Test", reason="pilot: Jobs only"))
        self._outbound()
        self._hierarchy()
        self._items()
        self.db.add(models.PackageLookupCache(feed_url_normalised=f"https://feed.client-a.example/{tag}",
                                              package_id="EnterpriseLibrary.Common", versions=["6.0.1304.0"],
                                              metadata_={"6.0.1304.0": {"dependencyFrameworks": ["net45"],
                                                                        "libFrameworks": ["net45"], "dependencies": []}},
                                              fetched_at=datetime.datetime.now(datetime.timezone.utc)))
        self.db.commit()

    def _outbound(self):
        def invocation(n, project, mechanism, host, bindings, sites, runtime=None):
            self.db.add(models.OutboundInvocation(
                id=f"{self.tag}-{n}", repository_id=self.repo.id, project_id=self.projects[project].id, mechanism=mechanism,
                usage="used", endpoint_host=host, resolution="resolved", detail={}, environment_bindings=bindings,
                call_sites=sites, linux_verdict="requires_change", linux_reasons=["Windows authentication"],
                runtime_verdict=runtime, confidence=1))
        binding = lambda f, key, deploy=False: {"environment": "Production", "sourceFile": f, "keyPath": key,   # noqa: E731
                                                "linuxVerdict": "requires_change",
                                                **({"deployParameter": "x"} if deploy else {})}
        # In scope, with one binding in its own file and one in the excluded project's: only its own is listed.
        invocation(1, JOBS, "database", "jobs-db.client-a.example",
                   [binding("Jobs/app.config", "connectionStrings/Jobs", deploy=True),
                    binding("Archive/app.config", "connectionStrings/Jobs", deploy=True)],
                   [{"sourceFile": "Jobs/Clock.cs", "line": 1}])
        # The excluded project's own: dropped, its file never named.
        invocation(2, ARCHIVE, "database", "archive-db.client-a.example",
                   [binding("Archive/app.config", "connectionStrings/Archive", deploy=True)],
                   [{"sourceFile": "Archive/Old.cs", "line": 4}])
        invocation(3, ARCHIVE, "soap_client", "archive-soap.client-a.example",
                   [{**binding("Archive/app.config", "system.serviceModel/client"),
                     "soap": {"binding": "basicHttpBinding", "securityMode": "Transport", "clientCredentialType": "Windows"}}],
                   [{"sourceFile": "Archive/Old.cs", "line": 9}], runtime="supported_with_caveat")

    def _hierarchy(self):
        def node(node_id, node_type, name, project=None, detail=None):
            self.db.add(models.HierarchyNode(repository_id=self.repo.id, node_id=node_id, node_type=node_type, name=name,
                                             status="checked", project_id=project, detail=detail or {}))
        def edge(src, dst):
            self.db.add(models.HierarchyEdge(repository_id=self.repo.id, from_node=src, to_node=dst, kind="assembly_reference",
                                             resolution="resolved", detail={}))
        for rel, project in self.projects.items():
            node(f"project:{rel.lower()}", "project", Path(rel).stem, project.id)
        assemblies = [
            (JOBS, "Microsoft.SqlServer.ManagedDTS", "13.0.0.0", "repository", "Dependencies/Microsoft.SqlServer.ManagedDTS.dll", True),
            (JOBS, "Microsoft.Practices.EnterpriseLibrary.Common", "6.0.0.0", "repository",
             "packages/EnterpriseLibrary.Common.6.0.1304.0/lib/NET45/Microsoft.Practices.EnterpriseLibrary.Common.dll", True),
            (JOBS, "Acme.Vendor", None, "repository", "Dependencies/Acme.Vendor.dll", True),
            (JOBS, "Sybase.AdoNet4.AseClient", None, "gac", None, None),
            (JOBS, "System.Configuration", None, "framework", None, None),
            (ARCHIVE, "Archive.Vendor", None, "repository", "Dependencies/Archive.Vendor.dll", True),
        ]
        for rel, name, version, location, where, exists in assemblies:
            node_id = f"assembly:{location}:{(where or name).lower()}"
            node(node_id, "assembly", name, detail={"assembly": {"assemblyName": name, "version": version, "location": location,
                                                                  "path": where, "exists": exists}})
            edge(f"project:{rel.lower()}", node_id)

    def _items(self):
        def found(item_id, project, file=None, value=None, line=None):
            item = self.db.get(models.CatalogItem, item_id)
            self.db.add(models.ItemOccurrence(
                repository_id=self.repo.id, project_id=self.projects[project].id, item_id=item_id, scope=item.scope,
                file_path=file, value=value, signal_registry_version="test", detection_state="found",
                evidence=[{"line_start": line, "value": value}] if line else None,
                detected_at=datetime.datetime.now(datetime.timezone.utc)))
        found("encoding-default", JOBS, "Jobs/Clock.cs", "Encoding.Default", 1)
        found("datetime-now-usage", JOBS, "Jobs/Clock.cs", "System.DateTime.Now", 1)
        found("windows-only-assembly-reference", JOBS)
        self.db.add(models.EngagementDecision(engagement_id=TEST_ENGAGEMENT_ID, item_id="encoding-default",
                                              resolution_id="explicit-utf8", status="approved",
                                              approver_name="Test", rationale="decided for the test"))

    def remove(self):
        self.db.rollback()
        if self.repo is not None and self.repo.id is not None:
            for table in ("item_occurrences", "outbound_invocations", "hierarchy_edges", "hierarchy_nodes", "conversion_scopes",
                          "conversion_results", "conversion_plans"):
                self.db.execute(text(f"delete from {table} where repository_id = :r"), {"r": self.repo.id})
            self.db.execute(text("delete from package_lookup_cache where feed_url_normalised = :f"),
                            {"f": f"https://feed.client-a.example/{self.tag}"})
            self.db.execute(text("delete from engagement_decisions where engagement_id = :e and item_id = 'encoding-default' "
                                 "and rationale = 'decided for the test'"), {"e": TEST_ENGAGEMENT_ID})
            self.db.execute(text("delete from projects where repository_id = :r"), {"r": self.repo.id})
            self.db.commit()
            root = Path(self.repo.local_path)
            for line in _git(root, "worktree", "list", "--porcelain").splitlines():
                if line.startswith("worktree ") and Path(line[9:]).resolve() != root.resolve():
                    _git(root, "worktree", "remove", "--force", line[9:])
            self.db.execute(text("delete from repositories where id = :r"), {"r": self.repo.id})
            self.db.commit()
            shutil.rmtree(convert.conversions_dir(TEST_ENGAGEMENT_ID, self.slug).parent, ignore_errors=True)
        self.engagement.remove()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def model(self) -> dict:
        return collect.collect(self.db, self.repo)

    def both(self, model: dict) -> dict[str, dict[str, str]]:
        return {engine: render.render(model, engine) for engine in engines.ENGINES}

    def addendum(self, files: dict[str, str]) -> str:
        return next(t for p, t in files.items() if p.endswith("assessment-addendum.md"))

    # ---- issue 3: scope

    def test_issue_3_outbound_and_soap_sections_list_only_in_scope_configuration(self):
        model = self.model()
        self.assertEqual([o["host"] for o in model["outbound"]], ["jobs-db.client-a.example"])
        self.assertEqual([b["file"] for b in model["outbound"][0]["bindings"]], ["Jobs/app.config"])
        self.assertEqual(model["soap"], [])
        for engine, files in self.both(model).items():
            text_ = self.addendum(files)
            self.assertNotIn("Archive/app.config", text_, engine)
            self.assertNotIn("archive-db", text_, engine)
            self.assertIn("- `Jobs/app.config` key `connectionStrings/Jobs` (Production): a value is set", text_, engine)
            self.assertIn("This repository calls no SOAP backend.", text_, engine)

    def test_issue_3_a_work_items_files_never_name_a_restored_package_folder(self):
        model = self.model()
        item = next(i for i in model["items"] if i["id"] == "datetime-now-usage")
        files = render.concerned_files(model, item)
        self.assertIn("build/build.ps1", files)
        self.assertFalse([f for f in files if f.startswith("packages/")], files)
        self.assertFalse([f for f in files if f.startswith("Archive/")], files)

    def test_issue_3_an_unscoped_repository_keeps_every_entry(self):
        self.db.execute(text("delete from conversion_scopes where repository_id = :r"), {"r": self.repo.id})
        self.db.commit()
        model = self.model()
        self.assertEqual(sorted(o["host"] for o in model["outbound"]),
                         ["archive-db.client-a.example", "archive-soap.client-a.example", "jobs-db.client-a.example"])
        self.assertEqual(len(model["soap"]), 1)
        jobs = next(o for o in model["outbound"] if o["host"] == "jobs-db.client-a.example")
        self.assertEqual(sorted(b["file"] for b in jobs["bindings"]), ["Archive/app.config", "Jobs/app.config"])

    # ---- issue 4: decided changes without guidance

    def test_issue_4_a_decided_change_without_guidance_is_never_told_leave_unchanged_and_is_warned(self):
        model = self.model()
        changed = next(i for i in model["items"] if i["id"] == "encoding-default")
        self.assertTrue(changed["decided"])
        self.assertIsNone(changed["resolution"]["guidance"])
        for engine, files in self.both(model).items():
            self.assertFalse([p for p in files if "explicit-utf8" in p], engine)   # no work item
            for path, body in files.items():
                self.assertNotIn("none: leave unchanged", body, (engine, path))
            self.assertIn(f"| {changed['name']} | {changed['resolution']['name']} | no instruction yet: do not change; a person "
                          "supplies it |", self.addendum(files), engine)
        warning = render.incomplete(model)
        line = f"{changed['name']}: {changed['resolution']['name']} (chosen) has no instruction yet; the engine is told not to change it"
        self.assertTrue(any(d.startswith(line) for d in warning["details"]), warning["details"])

    def test_issue_4_preparation_records_the_warning_for_the_conversion_tab(self):
        result = conversion_preparation.run(_context(self.repo.id))
        self.assertEqual(result.exit_status, "COMPLETED")
        attempt = json.loads((convert.conversions_dir(TEST_ENGAGEMENT_ID, self.slug) / conversion_preparation.LAST_PREPARE)
                             .read_text(encoding="utf-8"))
        self.assertEqual(attempt["status"], "prepared", attempt.get("message"))
        details = attempt["incomplete"]["details"]
        self.assertTrue(any(d.startswith("Encoding.Default") and "on the guidance allow-list: Changes stored bytes" in d
                            for d in details), details)
        self.assertTrue(any("no decision recorded for " in d and "a person decides the replacement before the conversion "
                            "is run" in d for d in details), details)
        self.assertTrue(any(d.startswith("Package management") for d in details) is False)   # no packages.config here
        record = convert.records(TEST_ENGAGEMENT_ID, self.slug)[-1]
        self.assertEqual(record["incompleteInputs"], attempt["incomplete"])
        self.assertTrue(any(m["item"] == "encoding-default" and m["missing"] == "resolution" for m in record["withoutGuidance"]))
        worktree = Path(record["worktree"])
        for engine_file in (".github/platform-inputs/assessment-addendum.md", f"{claude.INPUTS_DIR}/assessment-addendum.md"):
            self.assertNotIn("none: leave unchanged", (worktree / engine_file).read_text(encoding="utf-8"), engine_file)

    # ---- issue 2: assembly references

    def test_issue_2_assembly_references_each_with_its_verdict_and_the_projects_formats(self):
        model = self.model()
        by_name = {a["name"]: a for a in model["assembly_references"]}
        self.assertEqual(sorted(by_name), ["Acme.Vendor", "Microsoft.Practices.EnterpriseLibrary.Common",
                                           "Microsoft.SqlServer.ManagedDTS", "Sybase.AdoNet4.AseClient"])
        self.assertNotIn("Archive.Vendor", by_name)                       # the excluded project's are not listed
        self.assertNotIn("System.Configuration", by_name)                 # the framework's own
        dts, entlib = by_name["Microsoft.SqlServer.ManagedDTS"], by_name["Microsoft.Practices.EnterpriseLibrary.Common"]
        self.assertEqual((dts["kind"], dts["verdict"], dts["exists"]), ("repository", "windows-only", True))
        self.assertIn("SQL Server Integration Services runtime", dts["why"])
        self.assertEqual((by_name["Sybase.AdoNet4.AseClient"]["kind"], by_name["Sybase.AdoNet4.AseClient"]["verdict"]),
                         ("GAC", "windows-only"))
        self.assertEqual((by_name["Acme.Vendor"]["verdict"]), "unknown")
        # A HintPath into packages/<id>.<version>/ is that package, undeclared, looked up as one.
        self.assertEqual((entlib["kind"], entlib["verdict"]), ("packages folder", "package"))
        self.assertEqual(entlib["package"], {"id": "EnterpriseLibrary.Common", "version": "6.0.1304.0"})
        self.assertEqual(entlib["lookup"], {"known": True, "current_supported": False, "newest_supporting": None})
        self.assertEqual([(p["path"], p["format"], p["packages_config"]) for p in model["projects"]],
                         [(JOBS, "old-style", False)])
        for engine, files in self.both(model).items():
            text_ = self.addendum(files)
            self.assertIn(render.ASSEMBLY_HEADING, text_, engine)
            self.assertIn("| `Jobs/Jobs.csproj` | old-style | no |", text_, engine)
            self.assertIn("| `Jobs/Jobs.csproj` | Microsoft.SqlServer.ManagedDTS | 13.0.0.0 | repository: "
                          "`Dependencies/Microsoft.SqlServer.ManagedDTS.dll` | yes | needs a replacement on Linux", text_, engine)
            self.assertIn("a NuGet package referenced by path: declare it as a package reference `EnterpriseLibrary.Common`; "
                          "no version known to support net10.0 yet", text_, engine)
            self.assertIn("| `Jobs/Jobs.csproj` | Acme.Vendor | - | repository: `Dependencies/Acme.Vendor.dll` | yes | "
                          "unknown: check it builds and loads on Linux |", text_, engine)
            self.assertNotIn("Archive.Vendor", text_, engine)

    def test_issue_2_a_windows_only_reference_raises_the_decision_item_and_detection_reads_the_hierarchy(self):
        self.db.execute(text("delete from item_occurrences where repository_id = :r"), {"r": self.repo.id})
        self.db.commit()
        item_detection.detect_repository(self.db, self.db.get(models.Repository, self.repo.id))
        rows = {(o.item_id, o.project_id, o.detection_state) for o in
                self.db.query(models.ItemOccurrence).filter_by(repository_id=self.repo.id, item_id="windows-only-assembly-reference")}
        self.assertIn(("windows-only-assembly-reference", self.projects[JOBS].id, "found"), rows)
        self.assertIn(("windows-only-assembly-reference", self.projects[ARCHIVE].id, "checked_absent"), rows)
        found = self.db.query(models.ItemOccurrence).filter_by(repository_id=self.repo.id, project_id=self.projects[JOBS].id,
                                                                item_id="windows-only-assembly-reference").one()
        self.assertEqual(found.evidence[0]["actual"], "Microsoft.SqlServer.ManagedDTS; Sybase.AdoNet4.AseClient")
        self.db.commit()                                    # as the step commits: the model reads what detection wrote
        # Undecided, the inputs tell the engine not to change it, and preparation's warning says a person decides first.
        model = self.model()
        item = next(i for i in model["items"] if i["id"] == "windows-only-assembly-reference")
        self.assertFalse(item["decided"])
        self.assertEqual(item["resolution"]["id"], "decide-windows-only-replacement")
        # The decision names the assemblies it is about (2026-11-25): no SSIS reimplementation is chosen here, so the SSIS
        # runtime is one of them.
        self.assertIn(f"{item['name']}: no decision recorded for Microsoft.SqlServer.ManagedDTS, Sybase.AdoNet4.AseClient; a "
                      "person decides the replacement before the conversion is run, and the engine is told not to change it",
                      render.incomplete(model)["details"])

    def test_detection_without_a_dependency_hierarchy_does_not_claim_the_item_absent(self):
        self.db.execute(text("delete from hierarchy_edges where repository_id = :r"), {"r": self.repo.id})
        self.db.execute(text("delete from hierarchy_nodes where repository_id = :r"), {"r": self.repo.id})
        self.db.execute(text("delete from item_occurrences where repository_id = :r"), {"r": self.repo.id})
        self.db.commit()
        item_detection.detect_repository(self.db, self.db.get(models.Repository, self.repo.id))
        states = {o.detection_state for o in self.db.query(models.ItemOccurrence).filter_by(
            repository_id=self.repo.id, item_id="windows-only-assembly-reference")}
        self.assertEqual(states, {"not_checked"})
        self.db.rollback()

    # ---- the verifier with no test project

    def test_a_conversion_with_no_test_project_is_verified_with_every_other_check_reported(self):
        from app.engine import verifier
        from app.engine.verifier import rediscovery

        result = conversion_preparation.run(_context(self.repo.id))
        self.assertEqual(result.exit_status, "COMPLETED")
        record = convert.records(TEST_ENGAGEMENT_ID, self.slug)[-1]
        worktree = Path(record["worktree"])
        clock = worktree / "Jobs" / "Clock.cs"
        clock.write_text(clock.read_text(encoding="utf-8").replace("DateTime.Now", "DateTime.UtcNow"), encoding="utf-8")
        _git(worktree, "commit", "-qam", "applying-utc: Clock reads UtcNow")
        snapshot = {"model": {"items": [], "projects": [{"path": JOBS, "framework": "v4.7"}], "deltas": [], "packages": []},
                    "solution": None, "unit_test_projects": []}
        built = []

        def build_and_test(tree, solution, projects, out):
            built.append((Path(out).name, solution, list(projects)))
            return {"built": True, "buildExit": 0, "projects": {}, "trx": []}

        with mock.patch.object(rediscovery, "snapshot", return_value=snapshot), \
                mock.patch.object(verifier, "build_and_test", side_effect=build_and_test):
            report = convert.verify(self.db, TEST_ENGAGEMENT_ID, self.slug, record["branch"], refresh_baseline=True)
        ids = [c["id"] for c in report["checks"]]
        for check in ("converted", "scope", "clean", "diff", "kept", "deltas", "config", "canary", "same", "rediscovery"):
            self.assertIn(check, ids)
        clean = next(c for c in report["checks"] if c["id"] == "clean")
        self.assertEqual(clean["state"], "gap")
        self.assertIn("no test project found in in-scope.sln", clean["detail"])
        self.assertEqual(next(c for c in report["checks"] if c["id"] == "diff")["state"], "na")
        self.assertNotEqual(report["verdict"], "PROVEN")
        self.assertTrue(report["reasons"][0].startswith("Clean re-run: no test project found in in-scope.sln"), report["reasons"])
        self.assertIn(("clean", "in-scope.sln", []), built)                      # the build ran


class EngineGuidanceEditing(unittest.TestCase):
    """Issue 4, fix 3: an admin fills a gap in the catalog's editors, with the item's version check (every change is in
    the activity record, app.auth.http); guidance that is not self-contained is refused as a field error."""

    def setUp(self):
        from sqlalchemy.orm import Session

        from app.db import engine
        self.connection = engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.connection.close()

    def payload(self, resolution, guidance):
        from app.items import schemas as s
        return s.ResolutionWrite(name=resolution.name, description=resolution.description,
                                 target_description=resolution.target_description, consumer_impact=resolution.consumer_impact,
                                 effort=resolution.effort, is_default=resolution.is_default,
                                 linux_compatible=resolution.linux_compatible, container_ready=resolution.container_ready,
                                 notes=resolution.notes, status=resolution.status, engine_guidance=guidance)

    def test_an_admin_writes_a_resolutions_guidance_and_a_platform_reference_is_refused(self):
        from fastapi import HTTPException

        from app.items import baseline
        from app.routers import catalog_items

        item = self.db.get(models.CatalogItem, "msmq-usage")
        r = self.db.get(models.ItemResolution, "migrate-to-message-broker")
        self.assertIsNone(r.engine_guidance)
        with self.assertRaises(HTTPException) as refused:
            catalog_items.update_resolution("msmq-usage", r.id, self.payload(r, "Follow docs/28-ITEM-AND-CONVERSION-MODEL.md "
                                                                               "and the item-detection step."),
                                            db=self.db, if_match=str(item.edit_version))
        self.assertEqual(refused.exception.status_code, 422)
        detail = refused.exception.detail[0]
        self.assertEqual((detail["field"], detail["code"]), ("engine_guidance", "NOT_SELF_CONTAINED"))
        self.assertIn("platform document", detail["message"])
        version = str(item.edit_version)
        out = catalog_items.update_resolution("msmq-usage", r.id, self.payload(
            r, "Send each message to the broker topic named in configuration, in the same order."),
            db=self.db, if_match=version)
        self.assertTrue(out.engine_guidance.startswith("Send each message to the broker"))
        self.assertEqual(baseline.edit_state(self.db.get(models.ItemResolution, r.id)), "edited")   # a reseed keeps it
        with self.assertRaises(HTTPException) as stale:
            catalog_items.update_resolution("msmq-usage", r.id, self.payload(r, "Something else."), db=self.db,
                                            if_match=version)
        self.assertEqual(stale.exception.status_code, 409)

    def test_an_items_guidance_is_checked_the_same_way(self):
        from fastapi import HTTPException

        from app.items import schemas as s
        from app.routers import catalog_items

        item = self.db.get(models.CatalogItem, "fx47-class-library")
        payload = s.CatalogItemWrite(name=item.name, description=item.description, scope=item.scope, category=item.category,
                                     detection=item.detection, excluded_roles=item.excluded_roles, owner_team=item.owner_team,
                                     status=item.status, engine_guidance="See C:\\platform\\runs\\notes.txt first.")
        with self.assertRaises(HTTPException) as refused:
            catalog_items.update_item("fx47-class-library", payload, db=self.db, if_match=str(item.edit_version))
        self.assertEqual(refused.exception.detail[0]["field"], "engine_guidance")


class VerdictOrder(unittest.TestCase):
    def test_missing_tests_are_the_first_reason_and_hold_the_verdict_at_partly_proven(self):
        from app.engine.verifier import verdict

        checks = [{"id": "converted", "label": "Converted", "state": "pass", "detail": "ok"},
                  {"id": "clean", "label": "Clean re-run", "state": "gap", "detail": "no test project", "first": True},
                  {"id": "canary", "label": "Canary", "state": "na", "detail": "not run"}]
        self.assertEqual(verdict(checks), ("PARTLY PROVEN", ["Clean re-run: no test project"]))
        checks.insert(0, {"id": "config", "label": "Configuration files parse", "state": "fail", "detail": "broken"})
        found, reasons = verdict(checks)
        self.assertEqual((found, reasons[0]), ("NOT PROVEN", "Clean re-run: no test project"))


class RestoredPackageFolders(unittest.TestCase):
    """A real scan: a restored package folder (packages/<id>.<version>/) holds a project file, a C# file using
    DateTime.Now and a script; the repository's own project does too. Discovery records only the repository's own."""

    ENGAGEMENT = f"t-restored-{uuid.uuid4().hex[:6]}"

    @classmethod
    def setUpClass(cls):
        from app.repositories import service as repositories_service
        from app.repositories.schemas import RegisterLocalPathRequest
        from app.workflow.runtime import service as runtime

        cls.tmp = Path(tempfile.mkdtemp(prefix="restored-"))
        cls.root = cls.tmp / "restored"
        sdk = ('<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n    <TargetFramework>net8.0</TargetFramework>\n'
               '  </PropertyGroup>\n</Project>\n')
        clock = "public class Clock { public System.DateTime At() => System.DateTime.Now; }\n"
        for rel, body in {"src/App/App.csproj": sdk, "src/App/Clock.cs": clock,
                          "packages/Vendor.Lib.1.0.0/content/Vendor.csproj": sdk,
                          "packages/Vendor.Lib.1.0.0/content/Clock.cs": clock,
                          "packages/Vendor.Lib.1.0.0/tools/install.ps1": "Write-Host vendor\n"}.items():
            (cls.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (cls.root / rel).write_text(body, encoding="utf-8")
        _git(cls.root, "init", "-q", "-b", "main")
        _git(cls.root, "add", "-A", "-f")
        _git(cls.root, "commit", "-qm", "with a restored package folder")
        cls.db = SessionLocal()
        cls.db.add(models.Engagement(id=cls.ENGAGEMENT, client_name="Test engagement (restored packages)",
                                     target_platform="Linux / OpenShift Container Platform 4", default_posture="lift-and-shift"))
        cls.db.commit()
        cls.repo = repositories_service.register_local_path(cls.db, cls.db.get(models.Engagement, cls.ENGAGEMENT),
                                                            RegisterLocalPathRequest(source_type="local_path", local_path=str(cls.root)))
        cls.db.commit()
        with mock.patch.object(settings, "compare_public_nuget_feed", False):
            token = repositories_service.start_rescan(cls.repo)
            cls.db.commit()
            cls.execution = runtime.launch_job(cls.db, "phase0-repository-discovery", {
                "engagement_id": cls.ENGAGEMENT, "repository_id": str(cls.repo.id), "ingest_token": token,
                "lookup_offline": True, "prepare_conversion": False}, triggered_by="manual")
            cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        from app.deletion import service as deletion

        cls.db.rollback()
        engagement = cls.db.get(models.Engagement, cls.ENGAGEMENT)
        if engagement is not None:
            deletion.delete(cls.db, deletion.engagement_plan(cls.db, engagement), engagement.client_name, via="test")
        cls.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_no_project_and_no_item_is_detected_inside_a_restored_package_folder(self):
        self.assertEqual(self.execution.batch_status, "COMPLETED", self.execution.exit_message)
        projects = sorted(p.relative_path for p in self.db.query(models.Project).filter_by(repository_id=self.repo.id))
        self.assertEqual(projects, ["src/App/App.csproj"])
        found = sorted(o.file_path or "" for o in self.db.query(models.ItemOccurrence).filter_by(
            repository_id=self.repo.id, item_id="datetime-now-usage", detection_state="found"))
        self.assertEqual(found, ["src/App/Clock.cs"])
        anywhere = [o.file_path for o in self.db.query(models.ItemOccurrence).filter_by(repository_id=self.repo.id)
                    if o.file_path and o.file_path.startswith("packages/")]
        self.assertEqual(anywhere, [])
        signals = [s for (s,) in self.db.execute(text("SELECT source_path FROM fingerprint_signals WHERE repository_id = :r "
                                                      "AND source_path LIKE 'packages/%'"), {"r": self.repo.id})]
        self.assertEqual(signals, [])


if __name__ == "__main__":
    unittest.main()
