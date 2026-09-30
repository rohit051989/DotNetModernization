"""Project role — 28-ITEM-AND-CONVERSION-MODEL.md Part D.

Computed, not catalogued: derived deterministically from what steps 2 and 3
already recorded, so it needs no authoring surface. Six roles, decided in
this order (the first that applies wins):

| Role | Derivation |
|---|---|
| DEPLOYMENT | Out-of-scope structural type from step 2 (.dcproj, .wapproj, .wixproj, .deployproj), or a .sfproj |
| DATABASE | `structural_type: sql_database_project` |
| TEST | A test framework package (step 2) or a testing signal (step 3) |
| APPLICATION | An entry point (step 3), or `output_type` Exe/WinExe |
| LIBRARY | A fingerprinted .NET project that is none of the above |
| UNKNOWN | Anything else: a project step 3 could not analyse, or a non-.NET type |

Notes on the order and the rules:
- TEST comes before APPLICATION because Microsoft.NET.Test.Sdk makes a test
  project's OutputType Exe. A test project is not a deployable application.
- "Entry point" means any step 3 ENTRY_POINT signal, plus the hosting
  surfaces a .NET Framework web project has instead of one (.svc, .aspx,
  .asmx, Global.asax). Part D says entry points come from step 4's entry-point
  inventory; until that exists, these signals stand in for it.
- A web SDK project would count as APPLICATION by SDK alone, but step 2 does
  not record the SDK. Its host builder (WebApplication.CreateBuilder) is an
  entry point, so it lands in APPLICATION regardless.
- LIBRARY needs a fingerprint: with no step 3 analysis there is no evidence
  either way, so the project is UNKNOWN rather than assumed a library.

Repository-level signals are deliberately not used for role: a root
Dockerfile does not make every project an application.
"""

ROLES = ("TEST", "DEPLOYMENT", "DATABASE", "APPLICATION", "LIBRARY", "UNKNOWN")

DEPLOYMENT_STRUCTURAL_TYPES = frozenset(
    {"docker_compose_project", "windows_packaging_project", "wix_installer_project", "deployment_project"}
)
# Service Fabric application projects: Part D names them DEPLOYMENT, but step
# 2 has no structural type for them (they arrive as unknown_project), so the
# extension decides.
DEPLOYMENT_EXTENSIONS = frozenset({".sfproj"})
DATABASE_STRUCTURAL_TYPES = frozenset({"sql_database_project"})
DOTNET_STRUCTURAL_TYPES = frozenset({"csharp_project", "vb_project", "fsharp_project"})

TEST_PACKAGE_PREFIXES = ("xunit", "nunit", "mstest", "microsoft.net.test.sdk")
TEST_SIGNALS = frozenset(
    {"FACT_ATTRIBUTE", "TEST_ATTRIBUTE", "TEST_METHOD_ATTRIBUTE", "TEST_FIXTURE_ATTRIBUTE",
     "XUNIT_PACKAGE", "NUNIT_PACKAGE", "MSTEST_PACKAGE"}
)
HOSTING_SURFACE_SIGNALS = frozenset({"SVC_FILE", "ASPX_FILE", "ASMX_FILE", "GLOBAL_ASAX_FILE"})


def derive_role(project: dict, packages: list[str], project_signal_names: set[str], entry_point_signals: set[str]) -> tuple[str, str]:
    """(role, why). `project` carries structural_type, extension,
    output_type and fingerprinted (bool). `project_signal_names` are this project's own
    signals; `entry_point_signals` the subset in the ENTRY_POINT category."""
    structural_type = project["structural_type"]
    if structural_type in DEPLOYMENT_STRUCTURAL_TYPES:
        return "DEPLOYMENT", f"structural type {structural_type}"
    if (project.get("extension") or "").lower() in DEPLOYMENT_EXTENSIONS:
        return "DEPLOYMENT", f"extension {project['extension']}"
    if structural_type in DATABASE_STRUCTURAL_TYPES:
        return "DATABASE", f"structural type {structural_type}"

    test_packages = sorted(p for p in packages if p.lower().startswith(TEST_PACKAGE_PREFIXES))
    if test_packages:
        return "TEST", f"test package {test_packages[0]}"
    test_signals = sorted(project_signal_names & TEST_SIGNALS)
    if test_signals:
        return "TEST", f"signal {test_signals[0]}"

    if entry_point_signals:
        return "APPLICATION", f"entry point {sorted(entry_point_signals)[0]}"
    surfaces = sorted(project_signal_names & HOSTING_SURFACE_SIGNALS)
    if surfaces:
        return "APPLICATION", f"hosting surface {surfaces[0]}"
    if project["output_type"] in ("Exe", "WinExe"):
        return "APPLICATION", f"output type {project['output_type']}"

    if structural_type in DOTNET_STRUCTURAL_TYPES and project["fingerprinted"]:
        return "LIBRARY", "no entry point"
    if structural_type in DOTNET_STRUCTURAL_TYPES:
        return "UNKNOWN", "not fingerprinted by step 3"
    return "UNKNOWN", f"structural type {structural_type}"
