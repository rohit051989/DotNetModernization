"""A repository's toolchain check (Part P): its projects from the database, checked against this machine
(app.toolchain.machine, app.toolchain.needs), recorded for everyone, and read back.

- Checked on the machine the repository is registered on, the one that builds its baseline: after discovery (the
  conversion-preparation step), whenever its page is read there, and by the package step before it starts.
- Everyone else reads what that machine last recorded, with where and when.
- The projects are the ones in the conversion's scope (app.scope). A unit test project is one test-coverage-assessment
  classified as unit; it needs the ASP.NET Core or Windows Desktop runtime when it, or a project it references, uses
  that SDK. A legacy project is a web application project when its project file imports
  Microsoft.WebApplication.targets: read from the checkout, so only on its machine.
"""
import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.auth import machine as host_machine
from app.scope import service as scope_service
from app.toolchain import machine, needs

WEB_APPLICATION = "Microsoft.WebApplication.targets"


def projects_for(db: Session, repository: models.Repository) -> list[dict]:
    """The repository's projects in scope, as app.toolchain.needs takes them, by path."""
    excluded = scope_service.excluded_paths(db, repository.id)
    rows = db.execute(text("""
        SELECT id, relative_path, project_format, project_sdk, target_framework_raw, target_frameworks_raw
        FROM projects WHERE repository_id = :r ORDER BY relative_path"""), {"r": repository.id}).all()
    sdk = {r.id: r.project_sdk or "" for r in rows}
    references: dict = {}
    for source, target in db.execute(text("""
            SELECT r.source_project_id, r.referenced_project_id FROM project_references r
            JOIN projects p ON p.id = r.source_project_id
            WHERE p.repository_id = :r AND r.referenced_project_id IS NOT NULL"""), {"r": repository.id}):
        references.setdefault(source, []).append(target)
    # The test projects the baseline runs: recognised by what they reference, whatever their names (app.conversion.
    # testprojects), the same ones the package step and the verifier run.
    from app.conversion import planner

    unit = set(planner.test_projects_found(db, repository.id)["run"])
    root = Path(repository.local_path) if repository.local_path else None

    def sdks_reached(project_id) -> set[str]:
        seen, stack = set(), [project_id]
        while stack:
            current = stack.pop()
            if current not in seen:
                seen.add(current)
                stack += references.get(current, [])
        return {sdk.get(p, "") for p in seen}

    out = []
    for r in rows:
        if r.relative_path in excluded:
            continue
        legacy = r.project_format == "legacy_msbuild"
        reached = sdks_reached(r.id) if r.relative_path in unit else {sdk[r.id]}
        out.append({"path": r.relative_path,
                    "frameworks": list(r.target_frameworks_raw or ([r.target_framework_raw] if r.target_framework_raw else [])),
                    "legacy": legacy, "unitTest": r.relative_path in unit,
                    "aspnet": "Microsoft.NET.Sdk.Web" in reached,
                    "desktop": "Microsoft.NET.Sdk.WindowsDesktop" in reached,
                    "webApplication": legacy and _imports_web_targets(root, r.relative_path)})
    return out


def _imports_web_targets(root: Path | None, relative: str) -> bool:
    try:
        return root is not None and WEB_APPLICATION in (root / relative).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False


def check(db: Session, repository: models.Repository, facts: dict | None = None) -> dict:
    """The check on this machine, now (app.toolchain.needs.check)."""
    return needs.check(projects_for(db, repository), facts if facts is not None else machine.facts())


def record(db: Session, repository: models.Repository, result: dict | None = None) -> models.ToolchainCheck:
    """Records the check, as this machine made it (now, unless given). The caller commits."""
    result = result if result is not None else check(db, repository)
    row = db.get(models.ToolchainCheck, repository.id) or models.ToolchainCheck(repository_id=repository.id)
    row.host, row.ready, row.result = host_machine.hostname(), result["ready"], result
    row.checked_at = datetime.datetime.now(datetime.timezone.utc)
    db.add(row)
    return row


def current(db: Session, repository: models.Repository) -> tuple[dict | None, models.ToolchainCheck | None, bool]:
    """(the result, its row, whether it was checked just now). On the repository's own machine, checked now and
    recorded when it changed; elsewhere, what that machine last recorded (None before it ever checked)."""
    from app.results import held

    row = db.get(models.ToolchainCheck, repository.id)
    if held.elsewhere(repository.registered_host):
        return (row.result if row else None), row, False
    result = check(db, repository)
    if row is None or row.result != result or not host_machine.same(row.host, host_machine.hostname()):
        row = record(db, repository, result)
        db.commit()
    return result, row, True


def blocking(db: Session, repository: models.Repository) -> str | None:
    """Why the baseline cannot build or run its tests on this machine, or None: what the package step says instead
    of finding out half way. Recorded, and committed, as it is checked: the caller rolls back when this says why."""
    result = check(db, repository)
    record(db, repository, result)
    db.commit()
    return None if result["ready"] else result["summary"]
