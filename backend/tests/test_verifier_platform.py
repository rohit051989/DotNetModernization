"""The verifier's Windows-only API check (2026-11-25, the review hand-off's gap 4): it rebuilds the converted branch with
the platform compatibility analyzer (CA1416) on and lists each call to an API only supported on Windows, with file and
line, in VERIFICATION.md; any listed call keeps the verdict below PROVEN.

The converted fixture is a made-up job on the target framework that still writes to the Windows Event Log. Its package
(System.Diagnostics.EventLog) restores from the local package cache, as the step programs' builds do.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.engine import verifier
from tests.tiers import slow

PROJECT = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework></PropertyGroup>
  <ItemGroup><PackageReference Include="System.Diagnostics.EventLog" Version="10.0.8" /></ItemGroup>
</Project>
"""
PROGRAM = """using System.Diagnostics;

if (!EventLog.SourceExists("Job"))
{
    EventLog.CreateEventSource("Job", "Application");
}
EventLog.WriteEntry("Job", "finished");
return 0;
"""
CLEAN = """using System;

Console.Error.WriteLine("Information: finished");
return 0;
"""


class ParsingTheAnalyzersWarnings(unittest.TestCase):
    def test_each_call_is_listed_once_with_its_repository_path_and_line(self):
        log = ("  C:\\w\\src\\Job\\Program.cs(7,1): warning CA1416: 'EventLog.WriteEntry(string, string)' is only supported "
               "on: 'windows'. [C:\\w\\src\\Job\\Job.csproj]\n") * 2 + "  Build succeeded.\n"
        self.assertEqual(verifier.platform_findings(log, Path("C:/w")),
                         [{"file": "src/Job/Program.cs", "line": 7,
                           "message": "'EventLog.WriteEntry(string, string)' is only supported on: 'windows'."}])

    def test_the_markdown_lists_them_and_a_listed_call_keeps_the_verdict_below_proven(self):
        findings = [{"file": "src/Job/Program.cs", "line": 7, "message": "'EventLog.WriteEntry' is only supported on: 'windows'."}]
        text = "\n".join(verifier.platform_md(findings))
        self.assertIn("## Windows-only API calls", text)
        self.assertIn("| `src/Job/Program.cs` | 7 | 'EventLog.WriteEntry' is only supported on: 'windows'. |", text)
        self.assertEqual(verifier.platform_md([]), [])
        check = verifier._check("windows-apis", "Windows-only APIs", "gap", "1 call(s) remain")
        self.assertEqual(verifier.verdict([check])[0], "PARTLY PROVEN")
        self.assertIn("Windows-only APIs", verifier.__doc__)


@slow
class TheCheckOnAConvertedJob(unittest.TestCase):
    def setUp(self):
        if shutil.which("dotnet") is None:
            self.skipTest("no dotnet on this machine")
        self.tmp = Path(tempfile.mkdtemp(prefix="ca1416-"))
        (self.tmp / "Job").mkdir()
        (self.tmp / "Job" / "Job.csproj").write_text(PROJECT, encoding="utf-8")
        (self.tmp / "Job" / "Program.cs").write_text(PROGRAM, encoding="utf-8")
        restored = subprocess.run(["dotnet", "restore", "Job/Job.csproj", "-nologo"], cwd=self.tmp, capture_output=True, text=True)
        self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)

    def tearDown(self):
        shutil.rmtree(getattr(self, "tmp", Path("does-not-exist")), ignore_errors=True)

    def test_each_event_log_call_left_is_listed_with_file_and_line(self):
        out = self.tmp / "out"
        out.mkdir()
        check, findings = verifier.platform_check(self.tmp, "Job/Job.csproj", out)
        self.assertEqual(check["state"], "gap", check["detail"])
        self.assertEqual(sorted({(f["file"], f["line"]) for f in findings}), [("Job/Program.cs", 3), ("Job/Program.cs", 5),
                                                                                ("Job/Program.cs", 7)])
        self.assertTrue(all("only supported on: 'windows'" in f["message"] for f in findings), findings)
        self.assertTrue((out / "platform-analysis.log").is_file())
        self.assertEqual(verifier.verdict([check])[0], "PARTLY PROVEN")

    def test_a_job_with_no_windows_only_call_passes(self):
        (self.tmp / "Job" / "Program.cs").write_text(CLEAN, encoding="utf-8")
        out = self.tmp / "out"
        out.mkdir()
        check, findings = verifier.platform_check(self.tmp, "Job/Job.csproj", out)
        self.assertEqual((check["state"], findings), ("pass", []), check["detail"])


if __name__ == "__main__":
    unittest.main()
