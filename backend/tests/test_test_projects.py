"""Test projects recognised by what they are, never by their names (app.conversion.testprojects).

A project named *.Tests, *Test or with no special name is a test project when it references a test framework: in
SDK-style form a PackageReference, IsTestProject or the MSTest.Sdk project SDK; in legacy form packages.config or a
<Reference> to a test framework assembly. One whose tests test-coverage-assessment classified as integration,
functional or smoke only is not run; a project with no test framework is not one, whatever its name.

Run from backend/:  python -m unittest tests.test_test_projects -v
"""
import tempfile
import unittest
from pathlib import Path

from app.conversion import testprojects

SDK = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>
  <ItemGroup>{items}</ItemGroup>
</Project>
"""
LEGACY = """<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup><TargetFrameworkVersion>v4.8</TargetFrameworkVersion></PropertyGroup>
  <ItemGroup>{items}</ItemGroup>
</Project>
"""


class Recognised(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def project(self, path: str, text: str, packages_config: str | None = None) -> str:
        (self.root / path).parent.mkdir(parents=True, exist_ok=True)
        (self.root / path).write_text(text, encoding="utf-8")
        if packages_config is not None:
            (self.root / path).with_name("packages.config").write_text(
                f'<?xml version="1.0" encoding="utf-8"?>\n<packages>{packages_config}</packages>\n', encoding="utf-8")
        return path

    def test_every_name_in_sdk_style_and_legacy_form(self):
        found = {
            self.project("Sdk/Billing.Tests/Billing.Tests.csproj",
                         SDK.format(items='<PackageReference Include="xunit" Version="2.9.2" />')): "package xunit",
            self.project("Sdk/BillingTest/BillingTest.csproj",
                         SDK.format(items='<PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.12.0" />')):
                "package Microsoft.NET.Test.Sdk",
            self.project("Sdk/Checks/Checks.csproj",
                         SDK.format(items='<PackageReference Include="NUnit" Version="4.2.2" />')): "package NUnit",
            self.project("Sdk/Verify/Verify.csproj", SDK.replace("<PropertyGroup>", "<PropertyGroup><IsTestProject>true"
                                                                                    "</IsTestProject>").format(items="")):
                "IsTestProject",
            self.project("Sdk/Probe/Probe.csproj", '<Project Sdk="MSTest.Sdk/3.6.4">\n</Project>\n'): "the MSTest.Sdk project SDK",
            self.project("Legacy/Ledger.Tests/Ledger.Tests.csproj", LEGACY.format(
                items='<Reference Include="Microsoft.VisualStudio.QualityTools.UnitTestFramework, Version=10.1.0.0" />')):
                "reference Microsoft.VisualStudio.QualityTools.UnitTestFramework",
            self.project("Legacy/LedgerTest/LedgerTest.csproj", LEGACY.format(
                items='<Reference Include="nunit.framework"><HintPath>..\\packages\\nunit.framework.dll</HintPath></Reference>')):
                "reference nunit.framework",
            self.project("Legacy/Reconcile/Reconcile.csproj", LEGACY.format(items='<Compile Include="Facts.cs" />'),
                         packages_config='<package id="MSTest.TestFramework" version="2.2.10" targetFramework="net48" />'):
                "package MSTest.TestFramework (packages.config)",
        }
        for path, why in found.items():
            self.assertEqual(testprojects.evidence(self.root / path), why, path)

    def test_a_name_alone_makes_nothing_a_test_project(self):
        for path in ("Sdk/Billing.UnitTests/Billing.UnitTests.csproj", "Sdk/Billing.Tests/Billing.Tests.csproj"):
            self.project(path, SDK.format(items='<PackageReference Include="xunit.abstractions" Version="2.0.3" />'))
            self.assertIsNone(testprojects.evidence(self.root / path))
        self.project("Legacy/App.Tests/App.Tests.csproj", LEGACY.format(items='<Reference Include="System.Data" />'))
        self.assertIsNone(testprojects.evidence(self.root / "Legacy/App.Tests/App.Tests.csproj"))
        self.assertIsNone(testprojects.evidence(self.root / "missing.csproj"))

    def test_integration_only_test_projects_are_not_run(self):
        xunit = SDK.format(items='<PackageReference Include="xunit" Version="2.9.2" />')
        for path in ("A.Tests/A.Tests.csproj", "B.IntegrationTests/B.IntegrationTests.csproj", "C/C.csproj", "Lib/Lib.csproj"):
            self.project(path, xunit if path != "Lib/Lib.csproj" else SDK.format(items=""))
        result = testprojects.found(self.root, ["Lib/Lib.csproj", "C/C.csproj", "B.IntegrationTests/B.IntegrationTests.csproj",
                                                "A.Tests/A.Tests.csproj"],
                                    {"A.Tests/A.Tests.csproj": {"unclassified"},
                                     "B.IntegrationTests/B.IntegrationTests.csproj": {"integration"},
                                     "C/C.csproj": {"unit", "integration"}})
        self.assertEqual(result["run"], ["A.Tests/A.Tests.csproj", "C/C.csproj"])
        self.assertEqual([n["path"] for n in result["notRun"]], ["B.IntegrationTests/B.IntegrationTests.csproj"])

    def test_the_projects_a_solution_lists(self):
        (self.root / "in-scope.sln").write_text(
            'Microsoft Visual Studio Solution File, Format Version 12.00\n'
            'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "A", "Source\\A\\A.csproj", "{1}"\nEndProject\n'
            'Project("{F184B08F-C81C-45F6-A57F-5ABD9991F28F}") = "B", "Source\\B\\B.vbproj", "{2}"\nEndProject\n'
            'Project("{2150E333-8FDC-42A3-9474-1A3956D46DE8}") = "Folder", "Folder", "{3}"\nEndProject\n', encoding="utf-8")
        self.assertEqual(testprojects.in_solution(self.root / "in-scope.sln"), ["Source/A/A.csproj", "Source/B/B.vbproj"])


if __name__ == "__main__":
    unittest.main()
