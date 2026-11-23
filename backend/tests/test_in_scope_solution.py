"""in-scope.sln for every conversion (36-COPILOT-ENHANCED-CONVERSION Part O, 2026-11-23), on a repository laid out as
solutions nested per job (Source/<area>/<job>/<job>.sln, each with C# projects) beside an SSIS solution (.dtproj,
.dtsx):

- with a full scope and with a reduced one, the conversion's solution lists exactly the .NET projects (.csproj, .vbproj)
  in scope, never the SSIS project, and builds with `dotnet build`;
- the SSIS project, and any other project that is not one, is listed as not converted by this track, by path, in both
  engines' instructions and in the runbook.

Project rows are fixture rows (tests/test_item_detection.DetectionTestCase), as solution-discovery records them; the
files are real, so the solution is built by the real .NET SDK when it is installed.
Run from backend/:  python -m unittest tests.test_in_scope_solution -v
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app import models
from app.engine import convert, engines
from app.engine.inputs import render
from app.scope import files as scope_files
from app.scope import service as scope_service
from tests.test_item_detection import DetectionTestCase

CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Library</OutputType></PropertyGroup>
</Project>
"""
DTPROJ = """<?xml version="1.0" encoding="utf-8"?>
<Project xmlns:SSIS="www.microsoft.com/SqlServer/SSIS"><DeploymentModel>Project</DeploymentModel></Project>
"""
JOBS = {"Source/Billing/Invoices/Invoices/Invoices.csproj": "Source/Billing/Invoices/Invoices.sln",
        "Source/Billing/Invoices/Invoices.Core/Invoices.Core.csproj": "Source/Billing/Invoices/Invoices.sln",
        "Source/Billing/Reminders/Reminders.csproj": "Source/Billing/Reminders/Reminders.sln",
        "Source/Ledger/Close/Close.csproj": "Source/Ledger/Close/Close.sln"}
SSIS = "Source/Warehouse/Loads/Loads.dtproj"


class InScopeSolution(DetectionTestCase):
    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="in-scope-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        for project in JOBS:
            (self.root / project).parent.mkdir(parents=True, exist_ok=True)
            (self.root / project).write_text(CSPROJ, encoding="utf-8")
            (self.root / project).with_name("Class1.cs").write_text("public class C { }\n", encoding="utf-8")
        (self.root / SSIS).parent.mkdir(parents=True, exist_ok=True)
        (self.root / SSIS).write_text(DTPROJ, encoding="utf-8")
        (self.root / SSIS).with_name("Load.dtsx").write_text("<DTS:Executable />\n", encoding="utf-8")
        self.repo.local_path = str(self.root)
        for path in [*JOBS, SSIS]:
            project = self.add_project(path)
            project.extension = Path(path).suffix
            if path == SSIS:
                project.structural_type, project.language = "ssis_project", "ssis"
        self.db.flush()

    def scope(self) -> dict:
        return scope_service.for_conversion(self.db, self.repo)

    def write_and_build(self, scope: dict) -> str:
        """Writes the scope's files into the fixture's root, as preparation does into the worktree; builds in-scope.sln."""
        for old in self.root.glob("in-scope.sln"):
            old.unlink()
        written = scope_files.write(self.root, scope)
        self.assertIn("in-scope.sln", written["written"])
        text = (self.root / "in-scope.sln").read_text(encoding="utf-8")
        if shutil.which("dotnet"):
            built = subprocess.run(["dotnet", "build", "in-scope.sln", "-nologo", "-v", "q"], cwd=self.root,
                                   capture_output=True, text=True, timeout=600)
            self.assertEqual(built.returncode, 0, built.stdout[-3000:] + built.stderr[-2000:])
        return text

    def test_a_full_scope_lists_every_dotnet_project_and_never_the_ssis_one(self):
        scope = self.scope()
        self.assertEqual(scope["build"], "in-scope.sln")
        self.assertEqual(scope["excluded"], [])
        self.assertEqual(sorted(p["path"] for p in scope["keptProjects"]), sorted(JOBS))
        self.assertEqual(scope["notConverted"], [{"path": SSIS, "name": "Loads"}])
        text = self.write_and_build(scope)
        for project in JOBS:
            self.assertIn(project.replace("/", "\\"), text)
        self.assertNotIn(".dtproj", text)
        self.assertFalse(list(self.root.rglob("OUT-OF-SCOPE.md")))        # nothing left out: no notes

    def test_a_reduced_scope_lists_exactly_the_kept_dotnet_projects(self):
        left = "Source/Ledger/Close/Close.csproj"
        self.db.add(models.ConversionScope(repository_id=self.repo.id, excluded_projects=[left],
                                           known_projects=[*JOBS, SSIS], saved_by_name="Reviewer", reason="Another track."))
        self.db.flush()
        scope = self.scope()
        self.assertEqual(scope["excluded"], [left])
        self.assertEqual(sorted(p["path"] for p in scope["keptProjects"]), sorted(p for p in JOBS if p != left))
        text = self.write_and_build(scope)
        self.assertNotIn("Close.csproj", text)
        self.assertNotIn(".dtproj", text)
        self.assertTrue((self.root / "Source/Ledger/Close/OUT-OF-SCOPE.md").is_file())

    def test_the_ssis_project_is_listed_as_not_converted_by_both_engines_and_the_runbook(self):
        scope = self.scope()
        model = {"scope": {"excluded": [], "build": scope["build"], "notConverted": scope["notConverted"]}}
        section = render.scope_section(model)
        self.assertIn("## Not converted by this track", section)
        self.assertIn(f"`{SSIS}`", section)
        self.assertIn("not in `in-scope.sln`", section)
        self.assertEqual(render.commands(model)["build"], "dotnet build in-scope.sln")
        record = {"repository": "fixture", "engagement": "e", "branch": "conversion/1", "worktree": str(self.root),
                  "solution": "in-scope.sln", "baseline": "0" * 40, "head": "1" * 40, "platform": {"commit": "a" * 16},
                  "goal": "Upgrade.", "targetFramework": "net10.0", "scope": scope,
                  "engines": {e: {"prepared": True, "usable": True} for e in engines.ENGINES}}
        runbook = convert.render_runbook(record)
        self.assertIn(f"`{SSIS}`", runbook.split("## A.")[0])
        self.assertIn(str(self.root / "in-scope.sln") if "\\" in str(self.root) else f"{self.root}/in-scope.sln", runbook)


if __name__ == "__main__":
    unittest.main()
