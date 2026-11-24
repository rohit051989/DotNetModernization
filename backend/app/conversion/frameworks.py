"""Which target frameworks a package version supports — the data that orders
package units around a retarget.

Same rule as dependency-assessment (Fingerprinting.Dependencies,
DependencyPipeline.Supports): a version with no framework groups at all is
framework-neutral; otherwise one of its dependency groups must be compatible
with the target, and the lib/ref frameworks are the second opinion. The
groups come from package_lookup_cache, which dependency-assessment filled.

Compatibility is NuGet's for the frameworks that occur here: a .NET (5+) or
.NET Core group is compatible with a .NET target of the same or a higher
version, a .NET Standard group up to 2.1 with any .NET 5+ target, `any` and
`agnostic` with everything. A .NET Framework group, or a platform-specific
one (net8.0-windows), is not compatible with a plain .NET target.

A .NET Framework target is the usual source of a modernization: `v4.7` or
`v4.7.2` as an old-style project records it (TargetFrameworkVersion), `net47`,
`net472` or `net48` as an SDK-style one does. A .NET Framework group of the same
or a lower version is compatible with it, a .NET Standard group as NuGet's table
says (netstandard2.0 from net461, 1.3 from net46, 1.0 from net45), `any` and
`agnostic`; a .NET (5+) or platform-specific group is not.
"""

import re
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models

_NETCORE = re.compile(r"^(?:net|netcoreapp)(\d+)\.(\d+)$")
_NETSTANDARD = re.compile(r"^netstandard(\d+)\.(\d+)$")
# .NET Framework: "v4.7", "v4.7.2" (an old-style project's TargetFrameworkVersion), "net47", "net472", "net48",
# "net403" (an SDK-style project's or a NuGet folder's short name). Never net5.0 and later: they have a dot.
_NETFX_OLD = re.compile(r"^v([1-4])\.(\d)(?:\.(\d))?$")
_NETFX_SHORT = re.compile(r"^net([1-4])(\d)(\d)?$")

# NuGet's table: the lowest .NET Framework that consumes each .NET Standard version (2.1 none).
_NETSTANDARD_FROM_NETFX = {(1, 0): (4, 5, 0), (1, 1): (4, 5, 0), (1, 2): (4, 5, 1), (1, 3): (4, 6, 0),
                           (1, 4): (4, 6, 1), (1, 5): (4, 6, 1), (1, 6): (4, 6, 1), (2, 0): (4, 6, 1)}


class UnknownFramework(ValueError):
    """A target framework none of the rules here covers. Package moves record such a package's dependencies and support
    as not known (app.conversion.planner.package_moves) instead of failing the plan or the inputs."""


def _parse(tfm: str) -> tuple[str, tuple[int, ...] | None]:
    t = tfm.strip().lower()
    if t in ("", "any", "agnostic"):
        return "any", None
    if "-" in t:
        return "platform", None   # net8.0-windows and the like
    if m := _NETCORE.match(t):
        major, minor = int(m.group(1)), int(m.group(2))
        if t.startswith("netcoreapp") or major >= 5:
            return "netcore", (major, minor)
    if m := _NETSTANDARD.match(t):
        return "netstandard", (int(m.group(1)), int(m.group(2)))
    if m := (_NETFX_OLD.match(t) or _NETFX_SHORT.match(t)):
        return "netfx", (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))
    return "other", None   # portable-*, monoandroid, ...


def is_netfx(tfm: str) -> bool:
    """A .NET Framework target, in either spelling."""
    return _parse(tfm)[0] == "netfx"


def compatible(target: str, group: str) -> bool:
    """Can a project targeting `target` (net8.0, net472, v4.7) consume a group built for `group`?"""
    kind, version = _parse(group)
    target_kind, target_version = _parse(target)
    if target_kind == "netcore":
        if kind == "any":
            return True
        if kind == "netcore":
            return version <= target_version
        if kind == "netstandard":
            return version <= (2, 1)
        return False
    if target_kind == "netfx":
        if kind == "any":
            return True
        if kind == "netfx":
            return version <= target_version
        if kind == "netstandard":
            lowest = _NETSTANDARD_FROM_NETFX.get(version)
            return lowest is not None and lowest <= target_version
        return False
    raise UnknownFramework(f"target {target} is neither .NET (5+) nor .NET Framework: its package support is not known")


@dataclass(frozen=True)
class Support:
    supported: bool | None    # None: not known — no data, or only an incompatible dependency group
    basis: str                # what the answer rests on


def supports(metadata: dict | None, target: str) -> Support:
    """From one version's cached metadata: {dependencyFrameworks, libFrameworks}."""
    if metadata is None:
        return Support(None, "no cached metadata for this version")
    deps = metadata.get("dependencyFrameworks") or []
    libs = metadata.get("libFrameworks")
    if deps and any(compatible(target, g) for g in deps):
        return Support(True, f"dependency group compatible with {target} ({', '.join(deps)})")
    if libs is not None:
        if not libs or any(compatible(target, g) for g in libs):
            return Support(True, f"lib/ref compatible with {target} ({', '.join(libs) or 'none: framework-neutral'})")
        return Support(False, f"no lib/ref group compatible with {target} ({', '.join(libs)})")
    if not deps:
        return Support(True, "no framework groups: framework-neutral")
    # dependency-assessment downloads lib/ref only for the newest version it
    # examines. Without it, an incompatible dependency group is not proof: an
    # MSBuild-targets package can declare a net472 group and install anywhere.
    return Support(None, f"only dependency group(s) {', '.join(deps)}, none compatible with {target}; lib/ref not examined")


def parse_version(version: str) -> tuple[int, ...]:
    """NuGet's numeric part, for ordering: "10.3.0-preview.1" -> (10, 3, 0)."""
    numbers = version.split("-")[0].split("+")[0].split(".")
    return tuple(int(n) for n in numbers if n.isdigit())


def range_minimum(nuget_range: str) -> tuple[int, ...] | None:
    """The lowest version a NuGet range allows — what restore picks: "[10.3.0, )" -> (10, 3, 0)."""
    lowest = nuget_range.strip().lstrip("[(").split(",")[0].rstrip("])").strip()
    return parse_version(lowest) if lowest else None


def _nearest_group(groups: list[dict], target: str) -> dict | None:
    """NuGet's nearest dependency group for a project on `target`: the most
    specific compatible one (.NET or .NET Framework before .NET Standard before any, highest version)."""
    ranked = []
    for group in groups:
        kind, version = _parse(group["framework"])
        if not compatible(target, group["framework"]):
            continue
        ranked.append(({"netcore": 3, "netfx": 3, "netstandard": 2, "any": 1}.get(kind, 0), version or (0, 0), group))
    return max(ranked, key=lambda r: (r[0], r[1]))[2] if ranked else None


def dependency_minimums(metadata: dict | None, target: str) -> dict[str, tuple[int, ...]] | None:
    """From one version's cached metadata (dependency-assessment 1.2.0 records
    the nuspec's groups): each dependency's minimum version, for a project on
    `target`. None when the dependencies were never recorded."""
    if metadata is None or metadata.get("dependencies") is None:
        return None
    group = _nearest_group(metadata["dependencies"], target)
    if group is None:
        return {}
    return {p["id"].lower(): m for p in group["packages"] if (m := range_minimum(p["range"])) is not None}


def version_metadata(db: Session, package_id: str, version: str) -> dict | None:
    """A version's cached metadata, from whichever feed cached it."""
    for row in db.query(models.PackageLookupCache).filter(func.lower(models.PackageLookupCache.package_id) == package_id.lower()):
        meta = (row.metadata_ or {}).get(version)
        if meta is not None:
            return meta
    return None
