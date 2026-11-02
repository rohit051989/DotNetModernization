"""What preparation writes into a conversion's worktree for its scope (36-COPILOT-ENHANCED-CONVERSION.md Part O), when
a project is left out: committed by the platform before the package step, so every build of the conversion, the
platform's and the agent's, builds only what is in scope.

- One solution filter (`<solution>.in-scope.slnf`, beside it) per solution that keeps a project, listing only the
  kept projects. Built with `dotnet build`/`dotnet test` like a solution.
- An `OUT-OF-SCOPE.md` in each excluded project's folder, never over a file already there: the project is outside
  this conversion's scope and left as it was, who decided, when, the reason when one was given, and that it is not
  part of the converted build.

Both are deterministic: the same scope writes the same bytes.
"""
import json
from pathlib import PurePosixPath

NOTE = "OUT-OF-SCOPE.md"
COMMIT_MESSAGE = "Conversion scope: solution filters for the kept projects, notes in the projects left untouched"


def _relative(solution: str, project: str) -> str:
    """The project's path from the solution's folder, with backslashes, as a solution lists it."""
    base = PurePosixPath(solution).parent.parts
    target = PurePosixPath(project).parts
    common = 0
    while common < min(len(base), len(target) - 1) and base[common] == target[common]:
        common += 1
    return "\\".join([".."] * (len(base) - common) + list(target[common:]))


def filter_text(solution: str, projects: list[str]) -> str:
    """A solution filter: the solution (by file name, from the filter's own folder) and the kept projects it lists."""
    listed = sorted((_relative(solution, p) for p in projects), key=str.lower)
    return json.dumps({"solution": {"path": PurePosixPath(solution).name, "projects": listed}}, indent=2) + "\n"


def note_text(projects: list[dict], scope: dict, filters: list[str]) -> str:
    """OUT-OF-SCOPE.md for the excluded projects ({path, name}) of one folder."""
    names = ", ".join(f"`{p['name']}`" for p in projects)
    one = len(projects) == 1
    out = ["# Outside this conversion's scope", "",
           f"{names} {'is' if one else 'are'} outside the scope of this conversion and left exactly as "
           f"{'it was' if one else 'they were'}. {'It is' if one else 'They are'} not part of the converted build: "
           + (f"the solution filter{'' if len(filters) == 1 else 's'} " + ", ".join(f"`{f}`" for f in filters)
              + f" leave{'s' if len(filters) == 1 else ''} {'it' if one else 'them'} out." if filters
              else f"no solution filter lists {'it' if one else 'them'}."),
           "", f"- Decided by: {scope.get('decidedBy') or 'unknown'}",
           f"- Decided on: {(scope.get('decidedAt') or '')[:10] or 'unknown'}"]
    if scope.get("reason"):
        out.append(f"- Reason: {scope['reason']}")
    out += ["", "Do not change " + ("this project" if one else "these projects") + " as part of this conversion.", ""]
    return "\n".join(out)


def planned(scope: dict) -> dict[str, str]:
    """{repository-relative path: text} of every scope file, for the scope's excluded projects and filters."""
    if not scope.get("excluded"):
        return {}
    filters = [f["filter"] for f in scope["filters"]]
    files = {f["filter"]: filter_text(f["solution"], f["projects"]) for f in scope["filters"]}
    folders: dict[str, list[dict]] = {}
    for p in scope["left"]:
        folders.setdefault(str(PurePosixPath(p["path"]).parent), []).append(p)
    for folder, projects in sorted(folders.items()):
        rel = NOTE if folder == "." else f"{folder}/{NOTE}"
        files[rel] = note_text(sorted(projects, key=lambda p: p["path"].lower()), scope, filters)
    return dict(sorted(files.items()))


def write(worktree, scope: dict) -> dict:
    """Writes the scope's files into the worktree: {written: [paths], kept: [paths already there, left as they were]}.
    A file already in the repository is never overwritten."""
    from app.conversion.gitops import expected_eols

    files = planned(scope)
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
