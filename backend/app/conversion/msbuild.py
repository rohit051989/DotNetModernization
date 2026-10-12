"""Where a project's target framework and its package versions are declared,
and the text edits that change them in place.

MSBuild resolves both from more than the project file: the target framework
can be set in an imported Directory.Build.props or Directory.Packages.props
(solution-discovery records which, as target_framework_source), and under
central package management a package's version is a <PackageVersion> in
Directory.Packages.props — often through an MSBuild property shared by a
family of packages ($(AspNetVersion)), and overridable per project with
VersionOverride. The edit goes where the value is declared, never into the
project file by assumption.

Edits are textual and minimal: the one attribute or element value changes;
formatting, comments and line endings stay as they were.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

_PROPERTY_REF = re.compile(r"^\$\((?P<name>[A-Za-z_][A-Za-z0-9_.-]*)\)$")


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig")


def write(path: Path, original_bytes: bytes, text: str) -> None:
    """Writes text back with the original BOM and line endings."""
    bom = original_bytes.startswith(b"\xef\xbb\xbf")
    crlf = b"\r\n" in original_bytes
    body = text.replace("\r\n", "\n")
    if crlf:
        body = body.replace("\n", "\r\n")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body.encode("utf-8"))


def nearest(root: Path, project_dir: Path, file_name: str) -> Path | None:
    """The file MSBuild imports by name: the nearest one at or above the
    project's directory, within the repository."""
    current = project_dir
    while True:
        candidate = current / file_name
        if candidate.exists():
            return candidate
        if current == root or root not in current.parents:
            return None
        current = current.parent


# ---------- target framework ----------

_TFM_ELEMENT = re.compile(r"<(?P<tag>TargetFrameworks?)>(?P<value>[^<]*)</(?P=tag)>")


@dataclass
class FrameworkDeclaration:
    file: str                  # repository-relative
    element: str               # TargetFramework or TargetFrameworks
    value: str
    projects: list[str] = field(default_factory=list)


def framework_declarations(root: Path, projects: list[dict]) -> list[FrameworkDeclaration]:
    """From solution-discovery's projects ({relative_path, target_framework_raw,
    target_framework_source}): the files that declare the framework."""
    found: dict[str, FrameworkDeclaration] = {}
    for project in projects:
        source = project.get("target_framework_source")
        if not source or not project.get("target_framework_raw"):
            continue
        project_path = root / project["relative_path"]
        file = project_path if source == "project" else nearest(root, project_path.parent, source)
        if file is None:
            raise FileNotFoundError(f"{project['relative_path']}: {source} not found above the project")
        rel = file.relative_to(root).as_posix()
        if rel not in found:
            match = _TFM_ELEMENT.search(read(file))
            if match is None:
                raise ValueError(f"{rel} declares no TargetFramework(s), though solution-discovery says it does")
            found[rel] = FrameworkDeclaration(rel, match.group("tag"), match.group("value").strip())
        found[rel].projects.append(project["relative_path"])  # not a JSON column: a FrameworkDeclaration
    return sorted(found.values(), key=lambda d: d.file)


def retarget(text: str, from_tfm: str, to_tfm: str) -> tuple[str, int]:
    """Replaces `from_tfm` by `to_tfm` inside every TargetFramework(s) element."""
    count = 0

    def swap(match):
        nonlocal count
        values = [v.strip() for v in match.group("value").split(";")]
        new = [to_tfm if v == from_tfm else v for v in values]
        count += sum(1 for a, b in zip(values, new) if a != b)
        return f"<{match.group('tag')}>{';'.join(new)}</{match.group('tag')}>"

    return _TFM_ELEMENT.sub(swap, text), count


def declared_frameworks(text: str) -> list[str]:
    return [v.strip() for m in _TFM_ELEMENT.finditer(text) for v in m.group("value").split(";")]


# ---------- package versions ----------

@dataclass
class VersionDeclaration:
    file: str                     # repository-relative file holding the value
    kind: str                     # property, package_version, version_override, package_reference
    name: str                     # the property's name, or the package id
    value: str                    # the declared version, resolved
    shared_with: list[str] = field(default_factory=list)   # other packages taking the same property

    @property
    def key(self) -> str:
        return f"{self.file}#{self.kind}:{self.name}"


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{name}\s*=\s*"([^"]*)"', tag)
    return m.group(1) if m else None


def _elements(text: str, element: str) -> list[re.Match]:
    return list(re.finditer(rf"<{element}\b[^>]*?/?>", text))


def _includes(tag: str, package_id: str) -> bool:
    include = _attr(tag, "Include") or _attr(tag, "Update") or ""
    return include.strip().lower() == package_id.lower()


def _property(text: str, name: str) -> str | None:
    m = re.search(rf"<{re.escape(name)}>([^<]*)</{re.escape(name)}>", text)
    return m.group(1).strip() if m else None


def version_declaration(root: Path, project_path: str, package_id: str) -> VersionDeclaration:
    """Where the version of `package_id` used by `project_path` is declared."""
    project_file = root / project_path
    project_text = read(project_file)
    for m in _elements(project_text, "PackageReference"):
        if _includes(m.group(0), package_id):
            override = _attr(m.group(0), "VersionOverride")
            if override:
                return VersionDeclaration(project_path, "version_override", package_id, override)
            version = _attr(m.group(0), "Version")
            if version and not _PROPERTY_REF.match(version):
                return VersionDeclaration(project_path, "package_reference", package_id, version)
    central = nearest(root, project_file.parent, "Directory.Packages.props")
    if central is None:
        raise LookupError(f"{project_path}: no version declared for {package_id}")
    central_text = read(central)
    rel = central.relative_to(root).as_posix()
    for m in _elements(central_text, "PackageVersion"):
        if _includes(m.group(0), package_id):
            version = _attr(m.group(0), "Version") or ""
            ref = _PROPERTY_REF.match(version)
            if not ref:
                return VersionDeclaration(rel, "package_version", package_id, version)
            name = ref.group("name")
            value = _property(central_text, name)
            holder = rel
            if value is None:
                build_props = nearest(root, project_file.parent, "Directory.Build.props")
                value = _property(read(build_props), name) if build_props else None
                holder = build_props.relative_to(root).as_posix() if build_props else rel
            if value is None:
                raise LookupError(f"{package_id}: version property $({name}) is not defined")
            sharing = sorted(
                (_attr(other.group(0), "Include") or "") for other in _elements(central_text, "PackageVersion")
                if (_attr(other.group(0), "Version") or "") == f"$({name})" and not _includes(other.group(0), package_id)
            )
            return VersionDeclaration(holder, "property", name, value, sharing)
    raise LookupError(f"{project_path}: no version declared for {package_id}")


def set_version(text: str, declaration: VersionDeclaration, to_version: str) -> tuple[str, bool]:
    """Changes the declared value; (new text, whether anything changed)."""
    if declaration.kind == "property":
        pattern = re.compile(rf"(<{re.escape(declaration.name)}>)([^<]*)(</{re.escape(declaration.name)}>)")
        new, n = pattern.subn(lambda m: m.group(1) + to_version + m.group(3), text, count=1)
        return new, n == 1 and new != text
    element = {"package_version": "PackageVersion", "package_reference": "PackageReference",
               "version_override": "PackageReference"}[declaration.kind]
    attribute = "VersionOverride" if declaration.kind == "version_override" else "Version"
    for m in _elements(text, element):
        if _includes(m.group(0), declaration.name):
            tag = re.sub(rf'(\b{attribute}\s*=\s*")[^"]*(")', lambda a: a.group(1) + to_version + a.group(2), m.group(0), count=1)
            return text[:m.start()] + tag + text[m.end():], tag != m.group(0)
    return text, False
