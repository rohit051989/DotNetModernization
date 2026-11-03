"""What this machine has for building and testing a repository on its own frameworks (Part P). Read from folders,
the dotnet executable's header and the registry: nothing is run, so it is quick enough for every page view.

- The .NET the platform builds and tests with: the `dotnet` first on PATH, which is DOTNET_ROOT's when backend/.env
  sets it (app.config.apply_dotnet_root). Its architecture, its SDKs, and its shared runtimes. `dotnet test` starts
  its test host from that install only: a runtime in another install does not count.
- The machine's other .NET installs (machine-wide x64 and x86, the per-user one), named only to say where a missing
  runtime is after all.
- The .NET Framework reference assemblies (the targeting packs), the newest .NET Framework runtime, and .NET Framework
  3.5.
- Microsoft.WebApplication.targets where `dotnet build` looks for it (the SDK's own MSBuild extensions folder), and
  where Visual Studio has it, which `dotnet build` does not use.

Standard library only.
"""
import os
import shutil
import struct
import sys
from pathlib import Path

ARCHITECTURES = {0x8664: "x64", 0x014C: "x86", 0xAA64: "arm64"}
FRAMEWORKS = ("Microsoft.NETCore.App", "Microsoft.AspNetCore.App", "Microsoft.WindowsDesktop.App")
EXECUTABLE = "dotnet.exe" if sys.platform == "win32" else "dotnet"
WEB_TARGETS = Path("WebApplications") / "Microsoft.WebApplication.targets"


def architecture(executable: Path) -> str | None:
    """x64, x86 or arm64, from a Windows executable's PE header; None when it is not one."""
    try:
        with open(executable, "rb") as f:
            head = f.read(4096)
        offset = struct.unpack_from("<I", head, 0x3C)[0]
        if head[offset:offset + 4] != b"PE\0\0":
            return None
        return ARCHITECTURES.get(struct.unpack_from("<H", head, offset + 4)[0])
    except (OSError, struct.error):
        return None


def _versions(folder: Path) -> list[str]:
    """The version folders in `folder` (8.0.29, 10.0.302), oldest first."""
    if not folder.is_dir():
        return []
    found = [p.name for p in folder.iterdir() if p.is_dir() and p.name[:1].isdigit()]
    return sorted(found, key=version_key)


def version_key(version: str) -> tuple:
    parts = []
    for part in version.replace("-", ".").split("."):
        parts.append((0, int(part)) if part.isdigit() else (1, part))
    return tuple(parts)


def install(root: Path) -> dict | None:
    """{root, architecture, sdks, runtimes: {framework: [versions]}, webTargets: [paths]} of a .NET install, or None."""
    if not (root / EXECUTABLE).is_file():
        return None
    return {"root": str(root), "architecture": architecture(root / EXECUTABLE),
            "sdks": _versions(root / "sdk"),
            "runtimes": {name: _versions(root / "shared" / name) for name in FRAMEWORKS},
            "webTargets": sorted(str(p) for p in (root / "sdk").glob(f"*/Microsoft/VisualStudio/v*/{WEB_TARGETS.as_posix()}"))}


def platform_root() -> Path | None:
    """The folder of the dotnet the platform builds with: the first on PATH (DOTNET_ROOT's, once applied)."""
    found = shutil.which("dotnet")
    return Path(found).resolve().parent if found else None


def _known_roots() -> list[Path]:
    roots = []
    for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        if os.environ.get(variable):
            roots.append(Path(os.environ[variable]) / "dotnet")
    if os.environ.get("USERPROFILE"):
        roots.append(Path(os.environ["USERPROFILE"]) / ".dotnet")
    if os.environ.get("DOTNET_ROOT"):
        roots.append(Path(os.environ["DOTNET_ROOT"]))
    return roots


def reference_assemblies() -> list[str]:
    """The .NET Framework versions whose reference assemblies are installed: v4.7.2 -> "4.7.2"."""
    base = Path(os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)") / "Reference Assemblies" / \
        "Microsoft" / "Framework" / ".NETFramework"
    if not base.is_dir():
        return []
    return sorted((p.name[1:] for p in base.iterdir() if p.is_dir() and p.name[:2] in ("v2", "v3", "v4")
                   and (p / "mscorlib.dll").is_file()), key=version_key)


def _registry(path: str, name: str):
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except (ImportError, OSError):
        return None


def netfx_release() -> int | None:
    """The installed .NET Framework 4.x release number (528040 and up: 4.8), or None."""
    value = _registry(r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full", "Release")
    return int(value) if value is not None else None


def visual_studio_web_targets() -> list[str]:
    found = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(variable):
            found += Path(os.environ[variable]).glob(
                f"Microsoft Visual Studio/*/*/MSBuild/Microsoft/VisualStudio/v*/{WEB_TARGETS.as_posix()}")
    return sorted(str(p) for p in found)


def facts() -> dict:
    """Everything above, for app.toolchain.needs.check."""
    used = platform_root()
    platform = install(used) if used else None
    others, seen = [], {str(used).lower()} if used else set()
    for root in _known_roots():
        key = str(root.resolve()).lower() if root.exists() else str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        if (found := install(root)) is not None:
            others.append(found)
    return {"dotnet": platform, "dotnetRootSet": bool(os.environ.get("DOTNET_ROOT")), "others": others,
            "referenceAssemblies": reference_assemblies(), "netfxRelease": netfx_release(),
            "netfx35": _registry(r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v3.5", "Install") == 1,
            "visualStudioWebTargets": visual_studio_web_targets()}
