"""Which projects are test projects, recognised by what they are, never by their names.

A test project references a test framework, which every .NET test runner needs:
- SDK-style: a PackageReference to Microsoft.NET.Test.Sdk, xunit, NUnit or MSTest (their core and runner packages
  included), `<IsTestProject>true</IsTestProject>`, or the MSTest.Sdk project SDK;
- legacy (.NET Framework): the same packages in its packages.config, or a `<Reference>` to a test framework assembly
  (Microsoft.VisualStudio.QualityTools.UnitTestFramework, Microsoft.VisualStudio.TestPlatform.TestFramework,
  nunit.framework, xunit, xunit.core).

A project named *.Tests, *Test or anything else is found the same way. The planner's baseline and the verifier run the
test projects found here, except one test-coverage-assessment classified as integration, functional or smoke tests and
nothing as unit tests: those need a running system (test_classes, 32-TEST-COVERAGE-ASSESSMENT.md Part B2).
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

TEST_PACKAGES = frozenset({
    "microsoft.net.test.sdk", "xunit", "xunit.core", "xunit.v3", "xunit.v3.core", "xunit.runner.visualstudio",
    "nunit", "nunit3testadapter", "nunit.testadapter", "mstest", "mstest.testframework", "mstest.testadapter",
    "mstest.sdk",
})
TEST_ASSEMBLIES = frozenset({
    "microsoft.visualstudio.qualitytools.unittestframework", "microsoft.visualstudio.testplatform.testframework",
    "nunit.framework", "xunit", "xunit.core",
})
NOT_RUN_TYPES = ("integration", "functional", "smoke")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def evidence(project_file: Path) -> str | None:
    """Why `project_file` is a test project ("package xunit", "IsTestProject", "reference nunit.framework", ...), or
    None when it is not one (or cannot be read)."""
    try:
        root = ET.fromstring(project_file.read_bytes())
    except (OSError, ET.ParseError):
        return None
    if (root.get("Sdk") or "").split("/")[0].strip().lower() == "mstest.sdk":
        return "the MSTest.Sdk project SDK"
    for element in root.iter():
        name = _local(element.tag)
        if name == "IsTestProject" and (element.text or "").strip().lower() == "true":
            return "IsTestProject"
        if name == "Sdk" and (element.get("Name") or "").strip().lower() == "mstest.sdk":
            return "the MSTest.Sdk project SDK"
        if name == "PackageReference":
            package = (element.get("Include") or element.get("Update") or "").strip()
            if package.lower() in TEST_PACKAGES:
                return f"package {package}"
        if name == "Reference":
            assembly = (element.get("Include") or "").split(",")[0].strip()
            if assembly.lower() in TEST_ASSEMBLIES:
                return f"reference {assembly}"
    packages_config = project_file.parent / "packages.config"
    if packages_config.is_file():
        try:
            for package in ET.fromstring(packages_config.read_bytes()).iter("package"):
                if (package.get("id") or "").strip().lower() in TEST_PACKAGES:
                    return f"package {package.get('id')} (packages.config)"
        except ET.ParseError:
            pass
    return None


def found(root: Path, projects: list[str], classified: dict[str, set[str]] | None = None) -> dict:
    """{run: [the test projects to run], notRun: [{path, why}]}: each of `projects` (repository-relative) that is a
    test project (evidence), less those `classified` ({project: the test types test-coverage-assessment gave its
    classes}) as integration, functional or smoke tests only."""
    classified = classified or {}
    run, not_run = [], []
    for path in sorted(projects, key=str.lower):
        why = evidence(root / path)
        if why is None:
            continue
        types = classified.get(path) or set()
        if types & set(NOT_RUN_TYPES) and "unit" not in types:
            not_run.append({"path": path, "why": f"its tests are {', '.join(sorted(types & set(NOT_RUN_TYPES)))} "
                                                 "tests (test-coverage-assessment), which need a running system"})
            continue
        run.append(path)
    return {"run": run, "notRun": not_run}


def in_solution(solution_file: Path) -> list[str]:
    """The project paths a .sln lists, relative to its folder, with forward slashes (in-scope.sln is at the worktree's
    root, so they are repository-relative)."""
    try:
        text = solution_file.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    listed = re.findall(r'^Project\("[^"]+"\)\s*=\s*"[^"]*",\s*"([^"]+\.(?:cs|vb|fs)proj)"', text, re.M | re.I)
    return sorted({p.replace("\\", "/") for p in listed}, key=str.lower)
