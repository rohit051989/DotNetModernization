"""A repository's conversion scope (36-COPILOT-ENHANCED-CONVERSION.md Part O): which of its projects its conversions
cover. The rest are left untouched.

- The project is the unit of scope. A solution is a shortcut for its projects, in the UI; what is stored and checked
  is the projects alone, by path relative to the repository, so a rescan keeps the scope.
- No saved scope means every project is in scope: a repository nobody has reviewed converts exactly as before. Only
  exclusions are stored, so a project discovered after the save is in scope by default (and flagged "new since scope
  was set"), and an excluded project that no longer exists simply drops out.
- A save is checked whole: every kept project's dependencies (its project references, from solution-discovery) must
  be kept too, directly or through other projects, and at least one project must be kept. Every problem is listed at
  once; nothing is saved until there are none.
- A save names the version of the scope it was made from (app.auth.versions), and records who, from which machine,
  when and why.
"""
import datetime
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.auth import activity, versions
from app.auth import actor as actors
from app.errors import error, errors

SUBJECT = "conversion_scope"
LEAVE_UNTOUCHED = "leave_untouched"


def _projects(db: Session, repository_id) -> list[dict]:
    """Every project of the repository: {path, name, solutions, dependsOn, workItems}, by path."""
    rows = db.execute(text("""
        SELECT id, relative_path, name FROM projects WHERE repository_id = :r ORDER BY relative_path"""),
        {"r": repository_id}).all()
    by_id = {r.id: {"path": r.relative_path, "name": r.name, "solutions": [], "dependsOn": [], "workItems": 0}
             for r in rows}
    for project_id, solution in db.execute(text("""
            SELECT sp.project_id, s.relative_path FROM solution_projects sp JOIN solutions s ON s.id = sp.solution_id
            WHERE s.repository_id = :r AND sp.project_id IS NOT NULL ORDER BY s.relative_path"""), {"r": repository_id}):
        if project_id in by_id and solution not in by_id[project_id]["solutions"]:
            by_id[project_id]["solutions"].append(solution)
    for source, target in db.execute(text("""
            SELECT r.source_project_id, r.referenced_project_id FROM project_references r
            JOIN projects p ON p.id = r.source_project_id
            WHERE p.repository_id = :r AND r.referenced_project_id IS NOT NULL"""), {"r": repository_id}):
        if source in by_id and target in by_id and by_id[target]["path"] not in by_id[source]["dependsOn"]:
            by_id[source]["dependsOn"].append(by_id[target]["path"])
    # A work item is an item found in a project, counted as the work list counts it: not when every place is only
    # possible (resting on ambiguous evidence).
    for project_id, count in db.execute(text("""
            SELECT project_id, count(*) FROM (
                SELECT project_id, item_id FROM item_occurrences
                WHERE repository_id = :r AND detection_state = 'found'
                GROUP BY project_id, item_id HAVING bool_or(certainty <> 'possible')) w
            GROUP BY project_id"""), {"r": repository_id}):
        if project_id in by_id:
            by_id[project_id]["workItems"] = count
    projects = sorted(by_id.values(), key=lambda p: p["path"].lower())
    for p in projects:
        p["dependsOn"].sort(key=str.lower)
    return projects


def problems(projects: list[dict], excluded: set[str]) -> list[dict]:
    """Every reason the selection cannot be saved: {code, message, project?, dependency?, through?}. A kept project
    whose dependency is excluded, directly or through other excluded projects, is one problem per such dependency."""
    names = {p["path"]: p["name"] for p in projects}
    depends = {p["path"]: p["dependsOn"] for p in projects}
    kept = [p["path"] for p in projects if p["path"] not in excluded]
    out = []
    if not kept:
        out.append({"code": "NOTHING_KEPT", "message": "At least one project must be kept: a conversion with no project "
                                                       "converts nothing."})
    for project in kept:
        seen: set[str] = set()
        stack = [(d, []) for d in reversed(depends[project]) if d in excluded]
        while stack:
            dependency, through = stack.pop()
            if dependency in seen:
                continue
            seen.add(dependency)
            how = f", through {', '.join(names[t] for t in through)}" if through else ""
            out.append({"code": "DEPENDENCY_EXCLUDED", "project": project, "dependency": dependency, "through": through,
                        "message": f"{names[project]} is kept, but it depends on {names[dependency]}{how}, which is "
                                   f"excluded: keep {names[dependency]}, or exclude {names[project]} too."})
            stack += [(d, through + [dependency]) for d in reversed(depends[dependency]) if d in excluded]
    return out


def _saved(scope: models.ConversionScope | None) -> dict | None:
    if scope is None:
        return None
    return {"by": scope.saved_by_name, "on": scope.saved_on, "at": scope.saved_at.isoformat(), "reason": scope.reason}


def tree(db: Session, repository: models.Repository) -> dict:
    """The scope as the editor shows it: every solution with its projects, every project with its solutions, its
    dependencies, its work items, whether it is excluded and whether it is new since the scope was saved.

    Whole, not a page at a time: the editor checks a draft against every project's dependencies as people tick, and
    shows it 20 rows at a time. A project is a path, a name and its references, so even a large repository's is small."""
    scope = db.get(models.ConversionScope, repository.id)
    projects = _projects(db, repository.id)
    paths = {p["path"] for p in projects}
    excluded = set(scope.excluded_projects) & paths if scope else set()
    known = set(scope.known_projects) if scope else paths
    for p in projects:
        p["excluded"] = p["path"] in excluded
        p["new"] = scope is not None and p["path"] not in known
    solutions: dict[str, dict] = {}
    for p in projects:
        for s in p["solutions"]:
            name = s.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".sln")
            solutions.setdefault(s, {"path": s, "name": name, "projects": []})["projects"].append(p["path"])
    return {
        "version": scope.version if scope else 0,
        "saved": _saved(scope),
        "treatment": scope.treatment if scope else LEAVE_UNTOUCHED,
        "solutions": sorted(solutions.values(), key=lambda s: s["path"].lower()),
        "projects": projects,
        # Excluded at the last save and no longer in the repository: they drop out of the scope.
        "gone": sorted(set(scope.excluded_projects) - paths, key=str.lower) if scope else [],
        "totals": {"projects": len(projects), "kept": len(projects) - len(excluded), "excluded": len(excluded),
                   "workItemsOutOfScope": sum(p["workItems"] for p in projects if p["excluded"]),
                   "new": sum(1 for p in projects if p["new"])},
    }


def excluded_paths(db: Session, repository_id) -> set[str]:
    """The projects excluded now: saved as excluded, and still in the repository."""
    scope = db.get(models.ConversionScope, repository_id)
    if scope is None or not scope.excluded_projects:
        return set()
    present = set(db.execute(text("SELECT relative_path FROM projects WHERE repository_id = :r"),
                             {"r": repository_id}).scalars())
    return set(scope.excluded_projects) & present


SOLUTION = "in-scope.sln"


def _entries(db: Session, repository_id) -> dict[str, dict]:
    """{project path: {guid, type, solution}}: how the first solution listing a project (by solution path) lists it,
    for the conversion's own solution. A project no solution lists has no entry."""
    out: dict[str, dict] = {}
    for path, guid, kind, solution in db.execute(text("""
            SELECT p.relative_path, sp.project_guid, sp.project_type_guid, s.relative_path
            FROM solution_projects sp JOIN solutions s ON s.id = sp.solution_id JOIN projects p ON p.id = sp.project_id
            WHERE s.repository_id = :r ORDER BY lower(s.relative_path), s.relative_path"""), {"r": repository_id}):
        out.setdefault(path, {"guid": guid, "type": kind, "solution": solution})
    return out


def for_conversion(db: Session, repository: models.Repository) -> dict:
    """What a conversion is prepared with, and records: the projects left out ({path, name}), with who decided, when
    and why, and the conversion's own solution (`build`, at the repository's root) listing exactly the kept projects
    (`keptProjects`: {path, name, guid, type, solution}, how a solution of the repository lists each, if one does),
    wherever they live, each once. Every project is in scope, and there is no solution of its own, when none is
    excluded."""
    scope = db.get(models.ConversionScope, repository.id)
    projects = _projects(db, repository.id)
    excluded = excluded_paths(db, repository.id)
    out = {"excluded": sorted(excluded, key=str.lower), "projects": len(projects), "kept": len(projects) - len(excluded),
           "treatment": scope.treatment if scope else LEAVE_UNTOUCHED, "version": scope.version if scope else 0,
           "left": [], "build": None, "keptProjects": []}
    if not excluded:
        return out
    out.update(decidedBy=scope.saved_by_name, decidedAt=scope.saved_at.isoformat(timespec="seconds"), reason=scope.reason,
               left=[{"path": p["path"], "name": p["name"]} for p in projects if p["path"] in excluded])
    entries = _entries(db, repository.id)
    out["keptProjects"] = [{"path": p["path"], "name": p["name"], "guid": None, "type": None, "solution": None,
                            **entries.get(p["path"], {})} for p in projects if p["path"] not in excluded]
    out["build"] = SOLUTION
    return out


def owner(path: str, projects: list[str]) -> str | None:
    """The project a repository file belongs to: the one whose folder holds it most closely, or None."""
    best = None
    for project in projects:
        folder = project.rsplit("/", 1)[0] + "/" if "/" in project else ""
        if path.startswith(folder) and (best is None or len(folder) > len(best[0])):
            best = (folder, project)
    return best[1] if best else None


def save(db: Session, repository: models.Repository, excluded: list[str], reason: str | None,
         if_match: str | None) -> dict:
    """Saves the scope, or refuses with every problem listed (422 SCOPE_INVALID), a stale copy (409 STALE_COPY) or no
    version (428). Returns the projects newly excluded and re-included, for the caller's summary."""
    db.get(models.Repository, repository.id, with_for_update=True)      # one save at a time, a first one included
    scope = versions.locked(db, models.ConversionScope, repository.id)
    versions.check(db, scope.version if scope else None, if_match, SUBJECT, str(repository.id),
                   "this repository's conversion scope")
    projects = _projects(db, repository.id)
    paths = {p["path"] for p in projects}
    unknown = sorted(set(excluded) - paths)
    if unknown:
        raise error(422, f"Not saved: {len(unknown)} project(s) are not in this repository: {', '.join(unknown[:5])}. "
                         "Reload to see its projects as they are now.", field="excluded", code="UNKNOWN_PROJECT")
    wanted = set(excluded)
    found = problems(projects, wanted)
    if found:
        raise errors(422, [{"field": "excluded", **f, "code": "SCOPE_INVALID", "problem": f["code"]} for f in found])

    before = (set(scope.excluded_projects) & paths) if scope else set()
    who = actors.current() or actors.SYSTEM
    if scope is None:
        scope = models.ConversionScope(repository_id=repository.id, version=0)
        db.add(scope)
    scope.excluded_projects = sorted(wanted, key=str.lower)
    scope.known_projects = sorted(paths, key=str.lower)
    scope.treatment = LEAVE_UNTOUCHED
    scope.reason = (reason or "").strip() or None
    scope.saved_by, scope.saved_by_name, scope.saved_on = who.user_id, who.label(), who.hostname
    scope.saved_at = datetime.datetime.now(datetime.timezone.utc)
    scope.version = (scope.version or 0) + 1
    out_now, back_in = sorted(wanted - before, key=str.lower), sorted(before - wanted, key=str.lower)
    activity.record(db, "save conversion scope", SUBJECT, str(repository.id),
                    summary=f"{len(wanted)} of {len(paths)} project(s) excluded; {len(out_now)} newly excluded, "
                            f"{len(back_in)} re-included" + (f"; reason: {scope.reason}" if scope.reason else ""))
    db.commit()
    return {"newlyExcluded": out_now, "reIncluded": back_in, "version": scope.version}


def repository_or_404(db: Session, repository_id: uuid.UUID) -> models.Repository:
    repository = db.get(models.Repository, repository_id)
    if repository is None or repository.deleted_at is not None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")
    return repository
