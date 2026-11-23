"""What preparation writes into a conversion's worktree for its scope (36-COPILOT-ENHANCED-CONVERSION.md Part O):
committed by the platform before the package step, so every build of the conversion, the platform's and the agent's,
builds only what is in scope.

- The conversion's own solution, `in-scope.sln` at the repository's root, for every conversion: listing exactly the
  kept .NET projects (.csproj, .vbproj; app.scope.service.CONVERTIBLE), every one with a full scope: wherever they
  live, whichever solutions list them (each shared project once), and those no solution lists. Never an SSIS .dtproj or
  any other project that is not one: those are listed as not converted by this track instead. Built with
  `dotnet build`/`dotnet test` like any solution. A kept project keeps the GUID, type and Debug/Release configuration
  the first solution listing it gives it; one no solution lists gets a GUID made from its path and Debug/Release on
  Any CPU.
- An `OUT-OF-SCOPE.md` in each excluded project's folder, never over a file already there: the project is outside
  this conversion's scope and left as it was, who decided, when, the reason when one was given, and that it is not
  part of the converted build.

Both are deterministic: the same scope, at the same commit, writes the same bytes.
"""
import re
import uuid
from pathlib import Path, PurePosixPath

NOTE = "OUT-OF-SCOPE.md"
COMMIT_MESSAGE = "Conversion scope: a solution of the kept projects, notes in the projects left untouched"
# With nothing left out, the solution alone.
COMMIT_MESSAGE_FULL = "Conversion scope: a solution of the projects this conversion builds"
CONFIGURATIONS = ("Debug", "Release")
# A project's type in a solution, by its extension, when no solution of the repository lists it.
TYPES = {".csproj": "{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}", ".vbproj": "{F184B08F-C81C-45F6-A57F-5ABD9991F28F}",
         ".fsproj": "{F2A71F9B-5D33-465A-A702-920D77279786}", ".sqlproj": "{00D1A9C2-B5F0-4AF3-8072-F6C62B433612}"}


def _configurations(worktree: Path | None, solution: str | None, guid: str) -> dict[str, str]:
    """{Debug: its project configuration, Release: ...}: what the solution maps Debug|Any CPU and Release|Any CPU to
    for the project, else the same name on Any CPU."""
    text = ""
    if worktree is not None and solution and (worktree / solution).is_file():
        text = (worktree / solution).read_text(encoding="utf-8-sig", errors="replace")
    out = {}
    for name in CONFIGURATIONS:
        m = re.search(rf"^\s*{re.escape(guid)}\.{name}\|Any CPU\.ActiveCfg\s*=\s*(.+?)\s*$", text, re.M | re.I)
        out[name] = m.group(1) if m else f"{name}|Any CPU"
    return out


def _braced(guid: str | None) -> str | None:
    """A GUID as a solution writes it, `{ABC...}`, from solution-discovery's (without braces), or None if it is not one."""
    bare = (guid or "").strip("{}").upper()
    return "{" + bare + "}" if re.fullmatch(r"[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}", bare) else None


def solution_text(projects: list[dict], worktree: Path | None = None) -> str:
    """The conversion's own solution: every kept project ({path, name, guid, type, solution}), by path, each once."""
    used: set[str] = set()
    head, mapping = [], []
    for p in sorted(projects, key=lambda p: p["path"].lower()):
        listed = _braced(p.get("guid"))
        guid = listed if listed and listed not in used else None            # none, or copied from another project
        guid = guid or "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"in-scope.sln/{p['path']}")).upper() + "}"
        used.add(guid)
        kind = _braced(p.get("type")) or TYPES.get(PurePosixPath(p["path"]).suffix.lower(), TYPES[".csproj"])
        head += [f'Project("{kind}") = "{p["name"]}", "{p["path"].replace("/", chr(92))}", "{guid}"', "EndProject"]
        configs = _configurations(worktree, p.get("solution"), listed or guid)
        for name in CONFIGURATIONS:
            mapping += [f"\t\t{guid}.{name}|Any CPU.ActiveCfg = {configs[name]}",
                        f"\t\t{guid}.{name}|Any CPU.Build.0 = {configs[name]}"]
    out = ["", "Microsoft Visual Studio Solution File, Format Version 12.00", "# Visual Studio Version 17",
           "VisualStudioVersion = 17.0.31903.59", "MinimumVisualStudioVersion = 10.0.40219.1", *head, "Global",
           "\tGlobalSection(SolutionConfigurationPlatforms) = preSolution",
           *[f"\t\t{name}|Any CPU = {name}|Any CPU" for name in CONFIGURATIONS], "\tEndGlobalSection",
           "\tGlobalSection(ProjectConfigurationPlatforms) = postSolution", *mapping, "\tEndGlobalSection",
           "\tGlobalSection(SolutionProperties) = preSolution", "\t\tHideSolutionNode = FALSE", "\tEndGlobalSection",
           "EndGlobal", ""]
    return "\n".join(out)


def note_text(projects: list[dict], scope: dict) -> str:
    """OUT-OF-SCOPE.md for the excluded projects ({path, name}) of one folder."""
    names = ", ".join(f"`{p['name']}`" for p in projects)
    one = len(projects) == 1
    out = ["# Outside this conversion's scope", "",
           f"{names} {'is' if one else 'are'} outside the scope of this conversion and left exactly as "
           f"{'it was' if one else 'they were'}. {'It is' if one else 'They are'} not part of the converted build: "
           f"the conversion's solution, `{scope.get('build')}`, lists only the projects in scope.",
           "", f"- Decided by: {scope.get('decidedBy') or 'unknown'}",
           f"- Decided on: {(scope.get('decidedAt') or '')[:10] or 'unknown'}"]
    if scope.get("reason"):
        out.append(f"- Reason: {scope['reason']}")
    out += ["", "Do not change " + ("this project" if one else "these projects") + " as part of this conversion.", ""]
    return "\n".join(out)


def planned(scope: dict, worktree: Path | None = None) -> dict[str, str]:
    """{repository-relative path: text} of every scope file: the conversion's solution and the excluded projects'
    notes. `worktree`: where the repository's solutions are read for the kept projects' configurations."""
    if not scope.get("build"):
        return {}
    files = {scope["build"]: solution_text(scope["keptProjects"], worktree)}
    folders: dict[str, list[dict]] = {}
    for p in scope.get("left") or []:
        folders.setdefault(str(PurePosixPath(p["path"]).parent), []).append(p)
    for folder, projects in sorted(folders.items()):
        rel = NOTE if folder == "." else f"{folder}/{NOTE}"
        files[rel] = note_text(sorted(projects, key=lambda p: p["path"].lower()), scope)
    return dict(sorted(files.items()))


def write(worktree, scope: dict) -> dict:
    """Writes the scope's files into the worktree: {written: [paths], kept: [paths already there, left as they were]}.
    A file already in the repository is never overwritten."""
    from app.conversion.gitops import expected_eols

    files = planned(scope, worktree)
    written, kept = [], []
    eols = expected_eols(worktree, sorted(files))
    for rel, text in files.items():
        target = worktree / rel
        if target.exists():
            kept.append(rel)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline=eols[rel])
        written.append(rel)
    return {"written": written, "kept": kept}
