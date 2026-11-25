"""Which referenced assemblies only load on Windows (windows_only_assemblies.yaml, beside this file): read by the
conversion's inputs (app.engine.inputs.collect.assembly_references) and by item-detection, which raises the catalog item
windows-only-assembly-reference for a project that references one (app.steps.item_detection)."""
import functools
from pathlib import Path

import yaml

DATA = Path(__file__).resolve().parent / "windows_only_assemblies.yaml"


@functools.lru_cache(maxsize=1)
def _entries() -> tuple[dict, ...]:
    return tuple(yaml.safe_load(DATA.read_text(encoding="utf-8")).get("assemblies") or [])


def windows_only_by_project(db, repository_id) -> dict | None:
    """{project id: [simple names of the Windows-only assemblies it references]}, from dependency-hierarchy's
    assembly_reference edges (any location: a HintPath, the GAC). None when the repository has no dependency hierarchy:
    unknown, not "none"."""
    from sqlalchemy import text

    if db.execute(text("SELECT 1 FROM hierarchy_nodes WHERE repository_id = :r LIMIT 1"), {"r": repository_id}).first() is None:
        return None
    out: dict = {}
    for project_id, name in db.execute(text("""
            SELECT pn.project_id, a.name FROM hierarchy_edges e
            JOIN hierarchy_nodes pn ON pn.repository_id = e.repository_id AND pn.node_id = e.from_node AND pn.node_type = 'project'
            JOIN hierarchy_nodes a ON a.repository_id = e.repository_id AND a.node_id = e.to_node AND a.node_type = 'assembly'
            WHERE e.repository_id = :r AND e.kind = 'assembly_reference' AND pn.project_id IS NOT NULL
            ORDER BY a.name"""), {"r": repository_id}):
        if windows_only(name) and name not in out.setdefault(project_id, []):
            out[project_id].append(name)
    return out


def _entry(name: str | None) -> dict | None:
    simple = (name or "").split(",")[0].strip().lower()
    if not simple:
        return None
    for entry in _entries():
        listed = entry["name"].lower()
        if (simple == listed) if entry.get("match", "exact") == "exact" else simple.startswith(listed):
            return entry
    return None


def replaced_by(name: str | None) -> list[str]:
    """The catalog resolutions that replace the assembly `name` when a conversion chooses one (its entry's
    `replaced_by`): [] when none does, or the list does not name it."""
    return list((_entry(name) or {}).get("replaced_by") or [])


def windows_only(name: str | None) -> str | None:
    """Why the assembly `name` (its simple name) only loads on Windows, or None when the list does not name it."""
    simple = (name or "").split(",")[0].strip().lower()
    if not simple:
        return None
    for entry in _entries():
        listed = entry["name"].lower()
        if (simple == listed) if entry.get("match", "exact") == "exact" else simple.startswith(listed):
            return entry["why"]
    return None
