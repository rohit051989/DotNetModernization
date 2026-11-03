"""What a repository's baseline needs on the machine that builds it, and whether this machine has it (Part P).

The baseline builds every project in scope and runs the unit test projects, on the frameworks they target now:

- a modern project (netX.Y, netcoreappX.Y) needs a .NET SDK of that major version or later to build; a unit test
  project also needs that runtime, Microsoft.NETCore.App X.Y, in the architecture of the dotnet the platform builds
  with, and the ASP.NET Core or Windows Desktop runtime of the same version when it, or a project it references,
  is a web or desktop project;
- a legacy project (non-SDK-style, .NET Framework) needs that version's reference assemblies to build, and
  Microsoft.WebApplication.targets where `dotnet build` finds them when it is a web application project; a unit test
  project on .NET Framework needs that .NET Framework runtime (3.5 for 3.5 and older);
- an SDK-style project on .NET Framework needs a .NET SDK; its reference assemblies come from NuGet with the restore.

A project is {path, frameworks: [raw target frameworks], legacy, unitTest, aspnet, desktop, webApplication}. Standard
library only.
"""
import re

from app.toolchain.machine import version_key

_MODERN = re.compile(r"^net(?:coreapp)?(\d+)\.(\d+)(?:-[a-z0-9.]+)?$", re.I)
_FRAMEWORK_SHORT = re.compile(r"^net(\d)(\d)(\d?)$", re.I)
_FRAMEWORK_DOTTED = re.compile(r"^v(\d+(?:\.\d+)*)$", re.I)
RUNTIME_NAMES = {"Microsoft.NETCore.App": ".NET", "Microsoft.AspNetCore.App": "ASP.NET Core",
                 "Microsoft.WindowsDesktop.App": "Windows Desktop"}
ORDER = ("sdk", "reference-assemblies", "web-targets", "runtime", "netfx-runtime")
# The lowest .NET Framework 4.x release number of each version (Microsoft's "how to determine which versions").
NETFX_RELEASES = {"4.5": 378389, "4.5.1": 378675, "4.5.2": 379893, "4.6": 393295, "4.6.1": 394254, "4.6.2": 394802,
                  "4.7": 460798, "4.7.1": 461308, "4.7.2": 461808, "4.8": 528040, "4.8.1": 533320}


def framework(raw: str) -> tuple[str, str] | None:
    """("modern", "8.0") or ("framework", "4.7.2") for a raw target framework; None for netstandard and the unknown."""
    token = (raw or "").strip()
    if m := _MODERN.match(token):
        return "modern", f"{m.group(1)}.{m.group(2)}"
    if m := _FRAMEWORK_SHORT.match(token):
        return "framework", f"{m.group(1)}.{m.group(2)}" + (f".{m.group(3)}" if m.group(3) else "")
    if m := _FRAMEWORK_DOTTED.match(token):
        return "framework", m.group(1)
    return None


def needs(projects: list[dict]) -> list[dict]:
    """Every need, once, with the projects that have it: {key, kind, for: build|test, version, framework?, projects}."""
    found: dict[str, dict] = {}

    def add(key: str, path: str, **need):
        found.setdefault(key, {"key": key, **need, "projects": []})
        if path not in found[key]["projects"]:
            found[key]["projects"].append(path)

    for p in projects:
        for raw in p["frameworks"]:
            parsed = framework(raw)
            if parsed is None:
                if not p["legacy"]:
                    add("sdk", p["path"], kind="sdk", **{"for": "build"}, major=0)
                continue
            kind, version = parsed
            if kind == "modern":
                major = int(version.split(".")[0])
                add("sdk", p["path"], kind="sdk", **{"for": "build"}, major=0)
                found["sdk"]["major"] = max(found["sdk"]["major"], major)
                if p["unitTest"]:
                    for name, wanted in (("Microsoft.NETCore.App", True), ("Microsoft.AspNetCore.App", p["aspnet"]),
                                         ("Microsoft.WindowsDesktop.App", p["desktop"])):
                        if wanted:
                            add(f"runtime:{name}:{version}", p["path"], kind="runtime", **{"for": "test"},
                                framework=name, version=version)
            else:
                if p["legacy"]:
                    add(f"reference-assemblies:{version}", p["path"], kind="reference-assemblies", **{"for": "build"},
                        version=version)
                    if p["webApplication"]:
                        add("web-targets", p["path"], kind="web-targets", **{"for": "build"})
                else:
                    add("sdk", p["path"], kind="sdk", **{"for": "build"}, major=0)
                if p["unitTest"]:
                    add(f"netfx-runtime:{version}", p["path"], kind="netfx-runtime", **{"for": "test"}, version=version)
    return sorted(found.values(), key=lambda n: (n["for"], ORDER.index(n["kind"]),
                                                 list(RUNTIME_NAMES).index(n["framework"]) if "framework" in n else 0,
                                                 version_key(n.get("version") or "")))


def _join(labels: list[str]) -> str:
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


def _runtime_matches(versions: list[str], version: str) -> list[str]:
    """The installed versions a test host of `version` starts on: the same major, that minor or later."""
    major, minor = (int(x) for x in version.split("."))
    out = []
    for v in versions:
        parts = v.split(".")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit() and int(parts[0]) == major \
                and int(parts[1]) >= minor:
            out.append(v)
    return out


def _runtime_label(framework_name: str, version: str, arch: str) -> str:
    major, minor = version.split(".")
    shown = major if minor == "0" else version
    name = RUNTIME_NAMES[framework_name]
    if framework_name == "Microsoft.NETCore.App" and int(major) < 5:
        name = ".NET Core"
    return f"the {name} {shown} runtime ({arch})"


def _judge(need: dict, facts: dict) -> tuple[bool, str, str]:
    """(present, label, detail) of one need on this machine."""
    platform = facts.get("dotnet")
    arch = (platform or {}).get("architecture") or "x64"
    root = (platform or {}).get("root") or "no dotnet on PATH"
    kind = need["kind"]
    if kind == "sdk":
        major = need["major"]
        label = f"a .NET {major} SDK or later" if major else "a .NET SDK"
        sdks = (platform or {}).get("sdks") or []
        ok = any(v.split(".")[0].isdigit() and int(v.split(".")[0]) >= major for v in sdks)
        return ok, label, f"the platform builds with {root}, which has " + (
            f"the SDKs {', '.join(sdks)}" if sdks else "no SDK")
    if kind == "runtime":
        name, version = need["framework"], need["version"]
        label = _runtime_label(name, version, arch)
        have = ((platform or {}).get("runtimes") or {}).get(name) or []
        matching = _runtime_matches(have, version)
        if matching:
            return True, label, f"{root} ({arch}) has {', '.join(matching)}"
        detail = (f"`dotnet test` starts the test host from {root} ({arch}) only, which has "
                  + (f"{RUNTIME_NAMES[name]} {', '.join(have)}" if have else f"no {RUNTIME_NAMES[name]} runtime"))
        elsewhere = [(o, _runtime_matches((o.get("runtimes") or {}).get(name) or [], version))
                     for o in facts.get("others") or []]
        elsewhere = [(o, m) for o, m in elsewhere if m]
        if elsewhere:
            detail += "; " + "; ".join(f"{o['root']} ({o.get('architecture') or '?'}) has {', '.join(m)}"
                                       for o, m in elsewhere)
            if facts.get("dotnetRootSet") and any(o.get("architecture") == arch for o, _ in elsewhere):
                detail += (". DOTNET_ROOT (backend\\.env) points the platform at the install without it: install "
                           "the runtime there, or point DOTNET_ROOT at one that has it")
            elif all(o.get("architecture") != arch for o, _ in elsewhere):
                detail += f", which is not {arch}: install the {arch} runtime"
        return False, label, detail
    if kind == "reference-assemblies":
        version = need["version"]
        installed = facts.get("referenceAssemblies") or []
        return (version in installed, f"the .NET Framework {version} reference assemblies (its Developer Pack)",
                "installed: " + (", ".join(installed) if installed else "none"))
    if kind == "netfx-runtime":
        version = need["version"]
        label = f"the .NET Framework {version} runtime"
        if version_key(version) < version_key("4.0"):
            return bool(facts.get("netfx35")), label, ".NET Framework 3.5 is " + (
                "turned on" if facts.get("netfx35") else "not turned on (a Windows feature)")
        release = facts.get("netfxRelease")
        wanted = NETFX_RELEASES.get(version, 0)
        newest = max((v for v, r in NETFX_RELEASES.items() if release and release >= r), key=version_key, default=None)
        return (release is not None and release >= wanted, label,
                f"installed: .NET Framework {newest}" if newest else "no .NET Framework 4.5 or later is installed")
    if kind == "web-targets":
        found = (platform or {}).get("webTargets") or []
        visual_studio = facts.get("visualStudioWebTargets") or []
        detail = (f"dotnet build looks under {root}\\sdk\\<SDK version>\\Microsoft\\VisualStudio\\v<Visual Studio "
                  "version>\\WebApplications"
                  + (f"; Visual Studio has them at {visual_studio[0]}, which dotnet build does not use" if visual_studio else ""))
        return bool(found), "the web application build targets (Microsoft.WebApplication.targets) where dotnet build finds them", detail
    raise ValueError(f"unknown need {kind}")


def check(projects: list[dict], facts: dict) -> dict:
    """{ready, summary, missing: [...], present: [...], dotnet}: each need with its label, what it is for, the
    projects that have it, and what this machine has instead."""
    missing, present = [], []
    for need in needs(projects):
        ok, label, detail = _judge(need, facts)
        (present if ok else missing).append({"kind": need["kind"], "label": label, "for": need["for"],
                                             "projects": need["projects"], "detail": detail})
    build = [m["label"] for m in missing if m["for"] == "build"]
    test = [m["label"] for m in missing if m["for"] == "test"]
    if build and test:
        summary = f"The baseline cannot build here: needs {_join(build)}; its tests also need {_join(test)}"
    elif build:
        summary = f"The baseline cannot build here: needs {_join(build)}"
    elif test:
        summary = f"Baseline tests cannot run here: needs {_join(test)}"
    elif present:
        summary = "Ready: this machine has what the baseline needs to build and run its tests"
    else:
        summary = "Nothing to check: no project with a target framework this check knows"
    platform = facts.get("dotnet") or {}
    return {"ready": not missing, "summary": summary, "missing": missing, "present": present,
            "dotnet": {"root": platform.get("root"), "architecture": platform.get("architecture")}}
