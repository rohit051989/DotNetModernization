"""A synthetic repository of 170 projects for proving dependency-hierarchy at scale (37-DEPENDENCY-HIERARCHY.md Part H).

    python -m tests.fixtures.synthetic_repository <folder>
    python -m tests.fixtures.synthetic_repository --check <folder> <repository id>   (after registering and scanning it)

Writes, into an empty folder outside this repository:
- 170 project files: 20 applications (SDK-style web and workers, and legacy ASP.NET web applications), 115 libraries
  in four layers that reference each other (nested project references, and shared libraries every layer above uses),
  30 test projects, and 5 that are not code (database and shared projects);
- legacy projects with packages.config, assembly references to a DLL in the repository, to the GAC and to .NET
  Framework, and HintPaths into the packages folder; SDK-style projects with PackageReference, and a folder under
  central package management (Directory.Packages.props);
- one ProjectReference to a project file that is not there;
- NuGet.config naming one client feed, feeds/internal: the internal packages (SynthCo.Internal.*, which nuget.org does
  not have) and copies of the external ones the projects use (which it does), each with its nuspec dependencies;
- expected-graph.json: every project, and every edge the project files declare, as this generator wrote them — what
  the step's graph must match.

Nothing here contacts a network; the step later asks nuget.org about the packages' origin.
"""
import json
import sys
import zipfile
from pathlib import Path

# External packages (copies of real nuget.org packages, with simplified nuspec dependencies) and internal ones.
# id -> {version: [(dependency id, range), ...]}
EXTERNAL = {
    "Newtonsoft.Json": {"12.0.3": [], "13.0.3": []},
    "EntityFramework": {"6.4.4": []},
    "Serilog": {"2.12.0": [], "3.1.1": []},
    "Serilog.Sinks.Console": {"4.1.0": [("Serilog", "[2.10.0, )")]},
    "Microsoft.Extensions.Logging.Abstractions": {"8.0.0": [("Microsoft.Extensions.DependencyInjection.Abstractions", "[8.0.0, )")]},
    "Microsoft.Extensions.DependencyInjection.Abstractions": {"8.0.0": []},
    "Polly": {"7.2.4": []},
    "Dapper": {"2.1.35": []},
    "AutoMapper": {"12.0.1": [("Microsoft.CSharp", "[4.7.0, )")]},
    "Microsoft.CSharp": {"4.7.0": []},
    "Microsoft.NET.Test.Sdk": {"17.12.0": [("Microsoft.TestPlatform.TestHost", "[17.12.0, )"), ("Microsoft.CodeCoverage", "[17.12.0, )")]},
    "Microsoft.TestPlatform.TestHost": {"17.12.0": [("Microsoft.TestPlatform.ObjectModel", "[17.12.0, )")]},
    "Microsoft.TestPlatform.ObjectModel": {"17.12.0": []},
    "Microsoft.CodeCoverage": {"17.12.0": []},
    "xunit": {"2.9.2": [("xunit.core", "[2.9.2]"), ("xunit.assert", "[2.9.2]")]},
    "xunit.core": {"2.9.2": [("xunit.extensibility.core", "[2.9.2]")]},
    "xunit.extensibility.core": {"2.9.2": []},
    "xunit.assert": {"2.9.2": []},
}
INTERNAL = {
    "SynthCo.Internal.Logging": {"2.0.0": [("Serilog", "[2.12.0, )")], "2.1.0": [("Serilog", "[2.12.0, )")]},
    "SynthCo.Internal.Messaging": {"1.4.0": [("SynthCo.Internal.Logging", "[2.0.0, )"), ("Newtonsoft.Json", "[12.0.3, )")]},
    "SynthCo.Internal.Security": {"3.0.0": [("SynthCo.Internal.Logging", "[2.0.0, )"), ("Polly", "[7.2.4, )")]},
    "SynthCo.Internal.Data": {"1.1.0": [("SynthCo.Internal.Logging", "[2.0.0, )"), ("EntityFramework", "[6.4.4, )")]},
    "SynthCo.Internal.Contracts": {"5.2.0": [("SynthCo.Internal.Messaging", "[1.4.0, )")]},
}

CORE = [f"SynthCo.Core.{n}" for n in ("Common", "Abstractions", "Configuration", "Diagnostics", "Primitives", "Text", "Time", "Collections", "Caching", "Validation")]
DOMAIN = [f"SynthCo.Domain.{n:02d}" for n in range(1, 31)]
SERVICES = [f"SynthCo.Services.{n:02d}" for n in range(1, 41)]
DATA = [f"SynthCo.Data.{n:02d}" for n in range(1, 21)]           # legacy, packages.config
MODERN = [f"SynthCo.Modern.{n:02d}" for n in range(1, 16)]       # central package management
WEB_APPS = [f"SynthCo.Web.{n:02d}" for n in range(1, 6)]
WORKERS = [f"SynthCo.Worker.{n:02d}" for n in range(1, 6)]
LEGACY_APPS = [f"SynthCo.LegacyWeb.{n:02d}" for n in range(1, 11)]
TESTS = [f"SynthCo.Tests.{n:02d}" for n in range(1, 31)]
OTHER = [("SynthCo.Database.Main", ".sqlproj"), ("SynthCo.Database.Audit", ".sqlproj"), ("SynthCo.Database.Archive", ".sqlproj"),
         ("SynthCo.Shared.Assets", ".shproj"), ("SynthCo.Shared.Resources", ".shproj")]

LEGACY_WEB_GUIDS = "{349c5851-65df-11da-9384-00065b846f21};{fae04ec0-301f-11d3-bf4b-00c04f79efbc}"


def folder_of(name: str) -> str:
    layer = name.split(".")[1]
    return f"src/{layer}/{name}"


def path_of(name: str, extension: str = ".csproj") -> str:
    return f"{folder_of(name)}/{name}{extension}"


def nupkg(feed: Path, package_id: str, version: str, dependencies: list) -> None:
    deps = "".join(f'<dependency id="{d}" version="{r}" />' for d, r in dependencies)
    groups = "".join(f'<group targetFramework="{tfm}">{deps}</group>' for tfm in (".NETFramework4.8", "net8.0"))
    nuspec = (f'<?xml version="1.0" encoding="utf-8"?><package xmlns="http://schemas.microsoft.com/packaging/2013/05/nuspec.xsd">'
              f"<metadata><id>{package_id}</id><version>{version}</version><authors>synthetic</authors><description>{package_id}</description>"
              f"<dependencies>{groups}</dependencies></metadata></package>")
    with zipfile.ZipFile(feed / f"{package_id.lower()}.{version}.nupkg", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{package_id}.nuspec", nuspec)
        z.writestr("content/readme.txt", package_id)


def generate(root: Path) -> dict:
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"{root} is not empty: give an empty or new folder")
    root.mkdir(parents=True, exist_ok=True)
    feed = root / "feeds" / "internal"
    feed.mkdir(parents=True)
    for packages in (EXTERNAL, INTERNAL):
        for package_id, versions in packages.items():
            for version, dependencies in versions.items():
                nupkg(feed, package_id, version, dependencies)
    (root / "NuGet.config").write_text("""<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="internal" value="feeds/internal" />
  </packageSources>
</configuration>
""", encoding="utf-8")
    (root / "lib").mkdir()
    (root / "lib" / "Vendor.Reporting.dll").write_bytes(b"MZ synthetic")

    projects: list[dict] = []
    edges: list[dict] = []

    def project(name, kind, *, references=(), packages=(), legacy=False, central=False, output_type=None, sdk="Microsoft.NET.Sdk",
                framework="net8.0", assemblies=(), extra_reference=None):
        folder = root / folder_of(name)
        folder.mkdir(parents=True, exist_ok=True)
        items = []
        for reference in dict.fromkeys(references):                  # each once: two layer picks can coincide
            relative = Path("..", "..", Path(folder_of(reference)).relative_to("src"), f"{reference}.csproj")
            items.append(f'    <ProjectReference Include="{str(relative).replace("/", chr(92))}" />')
            edges.append({"from": path_of(name), "to": path_of(reference), "kind": "project_reference"})
        if extra_reference:
            items.append(f'    <ProjectReference Include="{extra_reference}" />')
        for package_id, version in packages:
            if legacy:
                kind_of_edge = "packages_config"
            elif central:
                items.append(f'    <PackageReference Include="{package_id}" />')
                kind_of_edge = "central_package_version"
            else:
                items.append(f'    <PackageReference Include="{package_id}" Version="{version}" />')
                kind_of_edge = "package_reference"
            edges.append({"from": path_of(name), "to": f"package:{package_id.lower()}@{version}", "kind": kind_of_edge})
        for include, hint in assemblies:
            items.append(f'    <Reference Include="{include}">' + (f"<HintPath>{hint}</HintPath>" if hint else "") + "</Reference>")
            simple = include.split(",")[0]
            if hint and "packages\\" in hint:
                continue                                              # the package's node stands for it
            if hint:                                                  # ..\..\..\lib\X.dll from src/<layer>/<name>
                target = "assembly:repository:" + hint.replace("\\", "/").removeprefix("../../../").lower()
            else:
                target = f"assembly:{'framework' if simple.startswith('System') else 'gac'}:{simple.lower()}"
            edges.append({"from": path_of(name), "to": target, "kind": "assembly_reference"})
        if legacy:
            body = f"""<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
    <OutputType>{output_type or "Library"}</OutputType>
    <AssemblyName>{name}</AssemblyName>
    <TargetFrameworkVersion>v4.8</TargetFrameworkVersion>
    {f"<ProjectTypeGuids>{LEGACY_WEB_GUIDS}</ProjectTypeGuids>" if kind == "application" else ""}
  </PropertyGroup>
  <ItemGroup>
{chr(10).join(items)}
  </ItemGroup>
</Project>
"""
            config = "\n".join(f'  <package id="{p}" version="{v}" targetFramework="net48" />' for p, v in packages)
            (folder / "packages.config").write_text(f'<?xml version="1.0" encoding="utf-8"?>\n<packages>\n{config}\n</packages>\n', encoding="utf-8")
        else:
            body = f"""<Project Sdk="{sdk}">
  <PropertyGroup>
    <TargetFramework>{framework}</TargetFramework>
    {f"<OutputType>{output_type}</OutputType>" if output_type else ""}
  </PropertyGroup>
  <ItemGroup>
{chr(10).join(items)}
  </ItemGroup>
</Project>
"""
        (folder / f"{name}.csproj").write_text(body, encoding="utf-8")
        projects.append({"path": path_of(name), "kind": kind, "legacy": legacy})

    # Libraries, bottom up. Core is shared by every layer above it.
    for i, name in enumerate(CORE):
        project(name, "library", references=CORE[:i][-2:], packages=[("Newtonsoft.Json", "13.0.3")] if i % 3 == 0 else [])
    for i, name in enumerate(DOMAIN):
        project(name, "library", references=[CORE[0], CORE[1 + i % 9]] + ([DOMAIN[i - 1]] if i % 4 else []),
                packages=[("SynthCo.Internal.Contracts", "5.2.0")] if i % 5 == 0 else [])
    for i, name in enumerate(SERVICES):
        project(name, "library", references=[DOMAIN[i % 30], DOMAIN[(i * 7) % 30], CORE[0]],
                packages=[("SynthCo.Internal.Messaging", "1.4.0"), ("Polly", "7.2.4")] if i % 2 == 0 else [("Serilog.Sinks.Console", "4.1.0")])
    for i, name in enumerate(DATA):
        project(name, "library", legacy=True, references=[DOMAIN[i % 30]],
                packages=[("EntityFramework", "6.4.4"), ("Newtonsoft.Json", "12.0.3"), ("SynthCo.Internal.Data", "1.1.0")],
                assemblies=[("System", None), ("System.Data", None),
                            ("Vendor.Licensing, Version=3.1.0.0, Culture=neutral, PublicKeyToken=0123456789abcdef", None),
                            ("Vendor.Reporting", r"..\..\..\lib\Vendor.Reporting.dll"),
                            ("Newtonsoft.Json, Version=12.0.0.0", r"..\..\..\packages\Newtonsoft.Json.12.0.3\lib\net45\Newtonsoft.Json.dll")])
    (root / "src" / "Modern").mkdir(parents=True, exist_ok=True)
    (root / "src" / "Modern" / "Directory.Packages.props").write_text("""<Project>
  <PropertyGroup><ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally></PropertyGroup>
  <ItemGroup>
    <PackageVersion Include="Microsoft.Extensions.Logging.Abstractions" Version="8.0.0" />
    <PackageVersion Include="Dapper" Version="2.1.35" />
    <PackageVersion Include="SynthCo.Internal.Security" Version="3.0.0" />
  </ItemGroup>
</Project>
""", encoding="utf-8")
    for i, name in enumerate(MODERN):
        project(name, "library", central=True, references=[SERVICES[i], SERVICES[(i + 20) % 40]],
                packages=[("Microsoft.Extensions.Logging.Abstractions", "8.0.0"), ("Dapper", "2.1.35")]
                + ([("SynthCo.Internal.Security", "3.0.0")] if i % 3 == 0 else []))

    # Applications on top: nested references down through every layer.
    for i, name in enumerate(WEB_APPS):
        project(name, "application", sdk="Microsoft.NET.Sdk.Web", references=[MODERN[i * 3], SERVICES[i * 8], CORE[0]],
                packages=[("AutoMapper", "12.0.1"), ("Serilog", "3.1.1")],
                extra_reference=r"..\..\Missing\SynthCo.Missing.csproj" if i == 0 else None)
    for i, name in enumerate(WORKERS):
        project(name, "application", output_type="Exe", references=[SERVICES[i * 8 + 1], MODERN[i * 3 + 1]],
                packages=[("SynthCo.Internal.Logging", "2.1.0")])
    for i, name in enumerate(LEGACY_APPS):
        project(name, "application", legacy=True, references=[DATA[i * 2], DATA[i * 2 + 1], SERVICES[i * 4]],
                packages=[("Newtonsoft.Json", "12.0.3"), ("SynthCo.Internal.Logging", "2.0.0")],
                assemblies=[("System", None), ("System.Web", None), ("Vendor.Reporting", r"..\..\..\lib\Vendor.Reporting.dll")])
    for i, name in enumerate(TESTS):
        target = (SERVICES + DATA + MODERN)[i * 2]
        project(name, "test", references=[target], packages=[("Microsoft.NET.Test.Sdk", "17.12.0"), ("xunit", "2.9.2")])
    for name, extension in OTHER:
        folder = root / folder_of(name)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}{extension}").write_text('<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003" />\n', encoding="utf-8")
        projects.append({"path": path_of(name, extension), "kind": "other", "legacy": True})

    expected = {
        "projects": sorted(projects, key=lambda p: p["path"]),
        "edges": sorted(edges, key=lambda e: (e["from"], e["to"], e["kind"])),
        "missing_reference": {"from": path_of(WEB_APPS[0]), "raw_path": r"..\..\Missing\SynthCo.Missing.csproj"},
    }
    (root / "expected-graph.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    return expected


def check(root: Path, repository_id: str) -> list[str]:
    """Compares the graph dependency-hierarchy wrote for the registered repository with expected-graph.json: every
    project once with its kind, every declared edge once, nothing declared that the files do not declare, each shared
    library a single node, and the missing reference a node not checked. Returns the differences."""
    from sqlalchemy import text
    from app.db import SessionLocal

    expected = json.loads((root / "expected-graph.json").read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        nodes = {r.node_id: r for r in db.execute(text(
            "SELECT node_id, node_type, status, detail FROM hierarchy_nodes WHERE repository_id = :rid"), {"rid": repository_id})}
        edges = [tuple(r) for r in db.execute(text(
            "SELECT from_node, to_node, kind FROM hierarchy_edges WHERE repository_id = :rid AND kind <> 'package_dependency'"),
            {"rid": repository_id})]
    finally:
        db.close()

    problems = []
    projects = {k: v for k, v in nodes.items() if v.node_type == "project"}
    for p in expected["projects"]:
        node = projects.get(f"project:{p['path']}")
        if node is None:
            problems.append(f"missing project {p['path']}")
        elif node.detail["project"]["kind"] != p["kind"]:
            problems.append(f"{p['path']}: kind {node.detail['project']['kind']}, expected {p['kind']}")
    want = {(f"project:{e['from']}", e["to"] if ":" in e["to"] else f"project:{e['to']}", e["kind"]) for e in expected["edges"]}
    have = set(edges)
    missing = want - have
    extra = {e for e in have - want if not e[1].endswith("Missing/SynthCo.Missing.csproj")}
    problems += [f"edge missing: {e}" for e in sorted(missing)] + [f"edge not declared: {e}" for e in sorted(extra)]
    if len(edges) != len(have):
        problems.append(f"{len(edges) - len(have)} edge(s) recorded more than once")
    gone = projects.get("project:src/Missing/SynthCo.Missing.csproj")
    if gone is None or gone.status != "not_checked":
        problems.append("the reference to a missing project is not a node marked not checked")
    return problems


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--check":
        found = check(Path(sys.argv[2]).resolve(), sys.argv[3])
        print("\n".join(found) if found else "the graph matches the project files: 0 differences")
        raise SystemExit(1 if found else 0)
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    result = generate(Path(sys.argv[1]).resolve())
    print(f"{len(result['projects'])} projects, {len(result['edges'])} declared edges")
