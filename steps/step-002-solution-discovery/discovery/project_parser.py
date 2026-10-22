"""Project file (`*proj`) discovery and MSBuild XML parsing. See
19-SOLUTION-DISCOVERY.md Parts D and F.

MSBuild XML is read for declared values only — conditions are never
evaluated and arbitrary `.props`/`.targets` imports are not followed. That is
a documented limitation (Part F), not a bug.

One exception, for the target framework: MSBuild implicitly imports the
nearest `Directory.Build.props` and `Directory.Packages.props` above a
project, and repositories commonly set `TargetFramework` once there
(eShopOnWeb does, in Directory.Packages.props). When the project file
declares no framework, those two files are read — unconditional, literal
properties only, `$(Name)` expanded from them — and the artifact records
which file the framework came from (`target_framework_source`).

Two more values are made known rather than left null, because every later
step treats null as "unknown" (item detection reports it as not_checked):

- `project_sdk`: the SDK the project file declares (`<Project Sdk="...">` or
  an `<Sdk Name="..."/>` child), without its version; `none` for a legacy
  MSBuild project, which has no SDK — a fact, not a gap.
- `output_type`: as declared; else from the implicit props files; else
  MSBuild's own default for the SDK — Exe for the Web, Worker and
  BlazorWebAssembly SDKs, Library otherwise. `output_type_source` records
  which: `project`, the props file, or `sdk_default`.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .encoding import read_text_detect_encoding
from .paths import walk_files

# Direct extension -> (structural_type, language) mapping. Anything else
# matching `*proj` is `unknown_project` / `unknown` — Part D.
EXTENSION_MAP = {
    ".csproj": ("csharp_project", "csharp"),
    ".vbproj": ("vb_project", "vb"),
    ".fsproj": ("fsharp_project", "fsharp"),
    ".sqlproj": ("sql_database_project", "sql"),
    ".dtproj": ("ssis_project", "ssis"),
    ".shproj": ("shared_project", "shared"),
    ".vcxproj": ("cpp_project", "cpp"),
}

# Known non-.NET project types that legitimately show up alongside a .NET
# estate — a Docker Compose orchestration file next to the services it
# composes, a Node.js frontend beside its .NET API. Recorded as present and
# out of scope, never as a parse failure — Part D.
OUT_OF_SCOPE_EXTENSION_MAP = {
    ".dcproj": ("docker_compose_project", "Docker Compose"),
    ".njsproj": ("nodejs_project", "Node.js"),
    ".pyproj": ("python_project", "Python"),
    ".esproj": ("javascript_project", "JavaScript"),
    ".wapproj": ("windows_packaging_project", "Windows Packaging"),
    ".wixproj": ("wix_installer_project", "WiX installer"),
    ".deployproj": ("deployment_project", "Deployment"),
    ".modelproj": ("modeling_project", "Modeling"),
}
OUT_OF_SCOPE_STRUCTURAL_TYPES = frozenset(
    structural_type for structural_type, _label in OUT_OF_SCOPE_EXTENSION_MAP.values()
)


def find_project_files(repo_root: Path) -> list[Path]:
    return sorted(p for p in walk_files(repo_root) if p.name.lower().endswith("proj"))


def _local_tag(element: ET.Element) -> str:
    tag = element.tag
    return tag.split("}", 1)[1] if "}" in tag else tag


def _first_property(root: ET.Element, tag_name: str) -> tuple[str | None, str | None]:
    """First unconditional occurrence of `<tag_name>` under any
    `<PropertyGroup>`, in document order. Falls back to the first
    conditioned occurrence (with a warning) when no unconditioned one
    exists. See Part F: "take the first unconditional occurrence and emit a
    parse warning" when a property appears under multiple conditions."""
    occurrences = []  # (is_conditioned, value)
    for group in root:
        if _local_tag(group) != "PropertyGroup":
            continue
        is_conditioned = "Condition" in group.attrib
        for child in group:
            if _local_tag(child) == tag_name and child.text is not None and child.text.strip():
                occurrences.append((is_conditioned, child.text.strip()))

    unconditioned = [value for conditioned, value in occurrences if not conditioned]
    if unconditioned:
        warning = None
        if len(set(unconditioned)) > 1:
            warning = f"'{tag_name}' has more than one unconditional value; used the first ('{unconditioned[0]}')"
        return unconditioned[0], warning

    if occurrences:
        value = occurrences[0][1]
        return value, f"'{tag_name}' only appears under a <PropertyGroup Condition=...>; used '{value}' without evaluating it"

    return None, None


# Implicit imports, in MSBuild's order: Directory.Build.props comes in via
# Microsoft.Common.props, Directory.Packages.props later via NuGet's props,
# so a value in the second overrides the first. Both precede the project
# body, so the project file's own value overrides both.
IMPLICIT_PROPS = ("Directory.Build.props", "Directory.Packages.props")
# MSBuild's OutputType when a project declares none: these SDKs set Exe in
# their own props; Microsoft.NET.Sdk and legacy projects default to Library.
SDK_DEFAULT_OUTPUT_TYPE = {
    "Microsoft.NET.Sdk.Web": "Exe",
    "Microsoft.NET.Sdk.Worker": "Exe",
    "Microsoft.NET.Sdk.BlazorWebAssembly": "Exe",
}
NO_SDK = "none"


def declared_sdk(root: ET.Element) -> str | None:
    """`<Project Sdk="Name/version;...">` or the first `<Sdk Name="..."/>`
    child: the SDK name without a version. None when neither is present."""
    value = root.attrib.get("Sdk")
    if not value:
        child = next((c for c in root if _local_tag(c) == "Sdk" and c.attrib.get("Name")), None)
        value = child.attrib["Name"] if child is not None else None
    if not value:
        return None
    return value.split(";")[0].split("/")[0].strip() or None


_PROPERTY_REF_RE = re.compile(r"\$\(([A-Za-z_][A-Za-z0-9_.\-]*)\)")


def _nearest_file(start: Path, repo_root: Path, name: str) -> Path | None:
    """The nearest `name` from the project's directory up to the repository
    root — MSBuild's own search stops at the first one found."""
    root = repo_root.resolve()
    directory = start.resolve()
    while True:
        candidate = directory / name
        if candidate.is_file():
            return candidate
        if directory == root or directory.parent == directory:
            return None
        directory = directory.parent


def _expand(value: str, properties: dict[str, tuple[str, str]]) -> str:
    for _ in range(5):
        expanded = _PROPERTY_REF_RE.sub(lambda m: properties[m.group(1)][0] if m.group(1) in properties else m.group(0), value)
        if expanded == value:
            break
        value = expanded
    return value


def implicit_properties(project_path: Path, repo_root: Path) -> dict[str, tuple[str, str]]:
    """Unconditional literal properties from the implicitly imported props
    files: name -> (value, repository-relative file that set it). Later
    imports override earlier ones, as MSBuild evaluates them."""
    properties: dict[str, tuple[str, str]] = {}
    for name in IMPLICIT_PROPS:
        path = _nearest_file(project_path.parent, repo_root, name)
        if path is None:
            continue
        try:
            text, _warning = read_text_detect_encoding(path)
            root = ET.fromstring(text)
        except (OSError, ET.ParseError):
            continue
        source = path.resolve().relative_to(repo_root.resolve()).as_posix()
        for group in root:
            if _local_tag(group) != "PropertyGroup" or "Condition" in group.attrib:
                continue
            for child in group:
                if "Condition" in child.attrib or child.text is None or not child.text.strip() or len(child):
                    continue
                properties[_local_tag(child)] = (_expand(child.text.strip(), properties), source)
    return properties


def _package_references(root: ET.Element) -> list[dict]:
    packages = []
    for item_group in root:
        if _local_tag(item_group) != "ItemGroup":
            continue
        for item in item_group:
            if _local_tag(item) != "PackageReference":
                continue
            name = item.attrib.get("Include") or item.attrib.get("Update")
            version = item.attrib.get("Version")
            if version is None:
                for child in item:
                    if _local_tag(child) == "Version" and child.text:
                        version = child.text.strip()
            packages.append(
                {
                    "package_name": name,
                    "version_raw": version,
                    "declaration_source": "packagereference",
                    "target_framework_raw": None,
                    "is_malformed": not bool(name),
                }
            )
    return packages


def _project_references(root: ET.Element) -> tuple[list[dict], list[str]]:
    """Each ProjectReference once, with a warning for each repeat. Two Includes naming the same file — the same
    text, or differing only in slash direction or case, which Windows MSBuild treats as one path — are one
    reference: the first is kept as written. Recording both would duplicate the reference (and an exact repeat
    would break uq_project_references_source_raw_path)."""
    references, warnings, seen = [], [], {}
    for item_group in root:
        if _local_tag(item_group) != "ItemGroup":
            continue
        for item in item_group:
            if _local_tag(item) != "ProjectReference":
                continue
            raw_path = item.attrib.get("Include")
            if not raw_path:
                continue
            key = raw_path.strip().replace("\\", "/").lower()
            if key in seen:
                same = "" if raw_path == seen[key] else f" (as '{seen[key]}')"
                warnings.append(f"ProjectReference '{raw_path}' is declared more than once{same}; recorded once")
                continue
            seen[key] = raw_path
            references.append({"raw_path": raw_path})
    return references, warnings


def _parse_packages_config(path: Path) -> tuple[list[dict], str | None]:
    try:
        text, encoding_warning = read_text_detect_encoding(path)
        root = ET.fromstring(text)
    except (OSError, ET.ParseError) as exc:
        return [], f"packages.config could not be parsed: {exc}"

    packages = []
    for package in root:
        if _local_tag(package) != "package":
            continue
        packages.append(
            {
                "package_name": package.attrib.get("id"),
                "version_raw": package.attrib.get("version"),
                "declaration_source": "packages_config",
                "target_framework_raw": package.attrib.get("targetFramework"),
                "is_malformed": not bool(package.attrib.get("id")),
            }
        )
    return packages, encoding_warning


def _base_result(name: str, relative_path: str, extension: str) -> dict:
    if extension in OUT_OF_SCOPE_EXTENSION_MAP:
        structural_type, _label = OUT_OF_SCOPE_EXTENSION_MAP[extension]
        language = "unknown"
    else:
        structural_type, language = EXTENSION_MAP.get(extension, ("unknown_project", "unknown"))
    return {
        "name": name,
        "relative_path": relative_path,
        "extension": extension,
        "structural_type": structural_type,
        "language": language,
        "project_format": "unknown",
        "assembly_name": None,
        "root_namespace": None,
        "output_type": None,
        "output_type_source": None,
        "project_sdk": None,
        "target_framework_raw": None,
        "target_frameworks_raw": None,
        "target_framework_source": None,
        "is_multi_targeting": False,
        "project_references": [],
        "packages": [],
        "package_management_style": "none",
        "has_packages_config": False,
        "parse_status": "failed",
        "parse_warnings": [],
    }


def parse(path: Path, repo_root: Path) -> dict:
    """Parses one project file. A known non-.NET type or a genuinely
    unrecognised extension is recorded and returned immediately — Part D:
    "Never silently skipped." Only a recognised .NET extension we actually
    attempt to parse can end up with `parse_status: failed`."""
    relative_path = path.relative_to(repo_root).as_posix()
    name = path.stem
    extension = path.suffix.lower()
    result = _base_result(name, relative_path, extension)

    if extension in OUT_OF_SCOPE_EXTENSION_MAP:
        _structural_type, label = OUT_OF_SCOPE_EXTENSION_MAP[extension]
        result["parse_status"] = "success"
        result["parse_warnings"] = [f"{label} project, recorded but not analysed (not a .NET project)"]
        return result

    if result["structural_type"] == "unknown_project":
        result["parse_status"] = "out_of_scope"
        result["parse_warnings"] = ["unrecognised project extension, recorded but not analysed"]
        return result

    warnings = []
    try:
        text, encoding_warning = read_text_detect_encoding(path)
        if encoding_warning:
            warnings.append(encoding_warning)
        root = ET.fromstring(text)
    except (OSError, ET.ParseError) as exc:
        result["parse_warnings"] = warnings + [f"parse failed: {exc}"]
        return result

    is_sdk_style = "Sdk" in root.attrib
    result["project_format"] = "sdk_style" if is_sdk_style else "legacy_msbuild"
    sdk = declared_sdk(root)
    result["project_sdk"] = sdk or NO_SDK
    implicit = implicit_properties(path, repo_root)

    for field, tag in (("assembly_name", "AssemblyName"), ("root_namespace", "RootNamespace"), ("output_type", "OutputType")):
        value, warning = _first_property(root, tag)
        result[field] = value
        if warning:
            warnings.append(warning)

    if result["output_type"]:
        result["output_type_source"] = "project"
    elif "OutputType" in implicit:
        result["output_type"], result["output_type_source"] = implicit["OutputType"]
    else:
        result["output_type"] = SDK_DEFAULT_OUTPUT_TYPE.get(sdk or "", "Library")
        result["output_type_source"] = "sdk_default"

    target_frameworks_raw = None
    framework_source = None
    names = ("TargetFrameworks", "TargetFramework") if is_sdk_style else ("TargetFrameworkVersion",)
    for tag in names:
        value, warning = _first_property(root, tag)
        if warning:
            warnings.append(warning)
        if value:
            framework_source = "project"
            break
    else:
        # Not in the project file: the implicitly imported props files.
        value = None
        for tag in names:
            if tag in implicit:
                value, framework_source = implicit[tag]
                break
    if value:
        value = _expand(value, implicit)
        if _PROPERTY_REF_RE.search(value):
            warnings.append(f"target framework '{value}' refers to a property not declared literally in the project or Directory.*.props; recorded unexpanded")
        if is_sdk_style:
            target_frameworks_raw = [v.strip() for v in value.split(";") if v.strip()]
        else:
            target_frameworks_raw = [value]

    result["target_frameworks_raw"] = target_frameworks_raw
    result["target_framework_source"] = framework_source if target_frameworks_raw else None
    result["target_framework_raw"] = target_frameworks_raw[0] if target_frameworks_raw else None
    result["is_multi_targeting"] = bool(target_frameworks_raw) and len(target_frameworks_raw) > 1

    packages = _package_references(root)
    result["project_references"], reference_warnings = _project_references(root)
    warnings.extend(reference_warnings)

    config_path = path.with_name("packages.config")
    has_packages_config = config_path.is_file()
    if has_packages_config:
        config_packages, config_warning = _parse_packages_config(config_path)
        if config_warning:
            warnings.append(config_warning)
        packages.extend(config_packages)

    has_package_reference = any(p["declaration_source"] == "packagereference" for p in packages)
    has_config_package = any(p["declaration_source"] == "packages_config" for p in packages)
    if has_package_reference and has_config_package:
        style = "mixed"
    elif has_package_reference:
        style = "packagereference"
    elif has_config_package:
        style = "packages_config"
    else:
        style = "none"

    result["packages"] = packages
    result["package_management_style"] = style
    result["has_packages_config"] = has_packages_config
    result["parse_status"] = "success"
    result["parse_warnings"] = warnings
    return result
