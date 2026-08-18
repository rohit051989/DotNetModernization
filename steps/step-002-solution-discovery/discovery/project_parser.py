"""Project file (`*proj`) discovery and MSBuild XML parsing. See
19-STEP-002-SOLUTION-DISCOVERY.md Parts D and F.

MSBuild XML is read for declared values only — conditions are never
evaluated and `.props`/`.targets` are never imported. That is a documented
limitation (Part F), not a bug.
"""

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


def _project_references(root: ET.Element) -> list[dict]:
    references = []
    for item_group in root:
        if _local_tag(item_group) != "ItemGroup":
            continue
        for item in item_group:
            if _local_tag(item) != "ProjectReference":
                continue
            raw_path = item.attrib.get("Include")
            if raw_path:
                references.append({"raw_path": raw_path})
    return references


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
        "target_framework_raw": None,
        "target_frameworks_raw": None,
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

    for field, tag in (("assembly_name", "AssemblyName"), ("root_namespace", "RootNamespace"), ("output_type", "OutputType")):
        value, warning = _first_property(root, tag)
        result[field] = value
        if warning:
            warnings.append(warning)

    target_frameworks_raw = None
    if is_sdk_style:
        multi, warning = _first_property(root, "TargetFrameworks")
        if warning:
            warnings.append(warning)
        if multi:
            target_frameworks_raw = [v.strip() for v in multi.split(";") if v.strip()]
        else:
            single, warning = _first_property(root, "TargetFramework")
            if warning:
                warnings.append(warning)
            if single:
                target_frameworks_raw = [single]
    else:
        single, warning = _first_property(root, "TargetFrameworkVersion")
        if warning:
            warnings.append(warning)
        if single:
            target_frameworks_raw = [single]

    result["target_frameworks_raw"] = target_frameworks_raw
    result["target_framework_raw"] = target_frameworks_raw[0] if target_frameworks_raw else None
    result["is_multi_targeting"] = bool(target_frameworks_raw) and len(target_frameworks_raw) > 1

    packages = _package_references(root)
    result["project_references"] = _project_references(root)

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
