"""`.sln` parsing — line-oriented, not XML. See
19-STEP-002-SOLUTION-DISCOVERY.md Part F.
"""

import re
from pathlib import Path

from .encoding import read_text_detect_encoding

SOLUTION_FOLDER_TYPE_GUID = "2150E333-8FDC-42A3-9474-1A3956D46DE8"

_FORMAT_VERSION_RE = re.compile(r"Format Version\s+([\d.]+)", re.IGNORECASE)
_VS_VERSION_RE = re.compile(r"^VisualStudioVersion\s*=\s*(.+)$", re.IGNORECASE)
_MIN_VS_VERSION_RE = re.compile(r"^MinimumVisualStudioVersion\s*=\s*(.+)$", re.IGNORECASE)
_PROJECT_LINE_RE = re.compile(
    r'^Project\("\{([0-9A-Fa-f-]+)\}"\)\s*=\s*"([^"]*)",\s*"([^"]*)",\s*"\{([0-9A-Fa-f-]+)\}"'
)
_NESTED_LINE_RE = re.compile(r"^\s*\{([0-9A-Fa-f-]+)\}\s*=\s*\{([0-9A-Fa-f-]+)\}\s*$")


def parse(path: Path, repo_root: Path) -> dict:
    """Parses one `.sln` file.

    Returns a dict: name, relative_path, format_version,
    visual_studio_version, minimum_vs_version, entries (list of
    {type_guid, name, raw_path, project_guid, is_folder}),
    nested (child_guid -> parent_guid, both upper-cased), parse_status,
    parse_error, warnings.
    """
    relative_path = path.relative_to(repo_root).as_posix()
    name = path.stem

    try:
        text, encoding_warning = read_text_detect_encoding(path)
    except OSError as exc:
        return _failed(name, relative_path, f"could not read file: {exc}")

    warnings = [encoding_warning] if encoding_warning else []

    format_version = None
    vs_version = None
    min_vs_version = None
    entries = []
    nested = {}
    in_nested_section = False

    for line in text.splitlines():
        stripped = line.strip()

        if format_version is None:
            match = _FORMAT_VERSION_RE.search(stripped)
            if match:
                format_version = match.group(1)
                continue

        match = _VS_VERSION_RE.match(stripped)
        if match:
            vs_version = match.group(1).strip()
            continue

        match = _MIN_VS_VERSION_RE.match(stripped)
        if match:
            min_vs_version = match.group(1).strip()
            continue

        match = _PROJECT_LINE_RE.match(stripped)
        if match:
            type_guid, proj_name, raw_path, proj_guid = match.groups()
            entries.append(
                {
                    "type_guid": type_guid.upper(),
                    "name": proj_name,
                    "raw_path": raw_path,
                    "project_guid": proj_guid.upper(),
                    "is_folder": type_guid.upper() == SOLUTION_FOLDER_TYPE_GUID,
                }
            )
            continue

        if stripped.startswith("GlobalSection(NestedProjects)"):
            in_nested_section = True
            continue
        if in_nested_section:
            if stripped == "EndGlobalSection":
                in_nested_section = False
                continue
            match = _NESTED_LINE_RE.match(stripped)
            if match:
                child, parent = match.groups()
                nested[child.upper()] = parent.upper()

    if format_version is None and not entries:
        return _failed(
            name,
            relative_path,
            "no 'Format Version' header and no Project entries found — not a recognisable .sln",
            warnings,
        )

    return {
        "name": name,
        "relative_path": relative_path,
        "format_version": format_version,
        "visual_studio_version": vs_version,
        "minimum_vs_version": min_vs_version,
        "entries": entries,
        "nested": nested,
        "parse_status": "success",
        "parse_error": None,
        "warnings": warnings,
    }


def _failed(name: str, relative_path: str, error: str, warnings: list[str] | None = None) -> dict:
    return {
        "name": name,
        "relative_path": relative_path,
        "format_version": None,
        "visual_studio_version": None,
        "minimum_vs_version": None,
        "entries": [],
        "nested": {},
        "parse_status": "failed",
        "parse_error": error,
        "warnings": warnings or [],
    }


def solution_folder_path(project_guid: str, nested: dict, folder_names_by_guid: dict) -> str | None:
    """Logical solution-folder path for a project entry — climbs the
    NestedProjects parent chain, joined by '/' outermost to innermost.
    None when the project sits at the solution root."""
    chain = []
    current = nested.get(project_guid)
    seen = set()
    while current and current not in seen:
        seen.add(current)
        folder_name = folder_names_by_guid.get(current)
        if folder_name is None:
            break
        chain.append(folder_name)
        current = nested.get(current)
    if not chain:
        return None
    return "/".join(reversed(chain))
