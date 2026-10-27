"""Hard delete of a repository from its engagement, or of a whole engagement (docs/VDI-SETUP.md: Deleting a repository or an engagement).

Engagement data, never the catalog: CLAUDE.md rule 7's "never hard-delete" is the catalog's rule, and stays so.

What goes:
- every database row that belongs to it: its own rows, everything that cascades from them, its workflow jobs (found
  through their parameters), its engine runs, and the integration rows that name it;
- its folders under RUNS_DIR: <engagement>/<repository>/ (and the engagement's experiments of it), or <engagement>/;
- in the registered checkout, the worktrees the platform made under that folder, and the branches the platform
  created there — the ones its records name (conversion records, package-step plans, engine runs, experiments).
  Never the repository itself, however it was registered: a clone the platform made from a URL stays exactly as a
  checkout registered by its path does. Never a branch no record names, nor one another registration of the same
  checkout also records.

What stays: the catalog, the package lookup cache, every other repository and engagement, and the engagement's estate
view, which still counts a deleted repository until the estate is consolidated again.

Order: refuse while one of its jobs runs; the checkout's worktrees and branches; the folders; then every row in one
transaction, with an audit row (deletion_audit) in the same transaction. If a file cannot be removed (a program holds
it open), nothing is deleted from the database and the deletion can simply be run again.
"""
import datetime
import getpass
import json
import os
import socket
import stat
import subprocess
from pathlib import Path

import yaml
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.config import settings

REPOSITORY_COLUMNS = ("repository_id", "caller_repository_id", "callee_repository_id", "declaring_repository_id",
                      "file_repository_id")
# Not referenced_project_id: another repository's reference to a deleted project is kept, set to null (its foreign key).
PROJECT_COLUMNS = ("project_id", "source_project_id", "from_project_id", "to_project_id", "declaring_project_id",
                   "caller_project_id", "callee_project_id")
# Engagement tables whose foreign key to engagements does not cascade: deleted before the engagement row.
ENGAGEMENT_NO_CASCADE = ("decision_records", "engagement_decisions", "engagement_item_scope",
                         "engagement_matrix_confirmations", "engagement_patterns", "engagement_probe_evidence",
                         "step_policies", "engine_runs")
NEVER = ("deletion_audit", "platform_heartbeat", "alembic_version")


class DeletionRefused(Exception):
    """Not deleted: a job is running, or the typed name does not match."""


class DeletionIncomplete(Exception):
    """Files could not be removed; nothing was deleted from the database. Close what holds them and run it again."""


# ---------------------------------------------------------------- what belongs to it

def _scope(db: Session, engagement: models.Engagement, repositories: list[models.Repository], whole: bool) -> dict:
    rids = [str(r.id) for r in repositories]
    instances = [str(i) for (i,) in db.execute(text(
        "SELECT id FROM wf_job_instances WHERE parameters->>'repository_id' = ANY(:r)"
        + (" OR parameters->>'engagement_id' = :e" if whole else "")), {"r": rids, "e": engagement.id})]
    executions = [str(i) for (i,) in db.execute(text(
        "SELECT id FROM wf_job_executions WHERE job_instance_id::text = ANY(:i)"), {"i": instances})]
    return {"engagement": engagement.id, "whole": whole, "rids": rids, "instances": instances, "executions": executions}


def _columns(db: Session) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for table, column in db.execute(text("SELECT table_name, column_name FROM information_schema.columns "
                                         "WHERE table_schema = current_schema()")):
        out.setdefault(table, set()).add(column)
    return out


def _where(table: str, cols: set[str], scope: dict) -> str | None:
    """The rows of `table` that belong to the scope, as SQL, or None when none can."""
    if table in NEVER:
        return None
    if table == "repositories":
        return "id::text = ANY(:rids)"
    if table == "engagements":
        return "id = :eid" if scope["whole"] else None
    if table == "wf_job_instances":
        return "id::text = ANY(:instances)"
    if table == "wf_job_executions":
        return "id::text = ANY(:executions)"
    if table in ("wf_step_executions", "wf_artifacts"):
        return "job_execution_id::text = ANY(:executions)"
    parts = []
    if scope["whole"] and "engagement_id" in cols:
        parts.append("engagement_id = :eid")
    parts += [f"{c}::text = ANY(:rids)" for c in REPOSITORY_COLUMNS if c in cols]
    parts += [f"{c} IN (SELECT id FROM projects WHERE repository_id::text = ANY(:rids))" for c in PROJECT_COLUMNS if c in cols]
    if "solution_id" in cols and table != "solutions":
        parts.append("solution_id IN (SELECT id FROM solutions WHERE repository_id::text = ANY(:rids))")
    if "plan_id" in cols:
        parts.append("plan_id IN (SELECT id FROM conversion_plans WHERE repository_id::text = ANY(:rids))")
    if table == "validation_queue":
        parts.append("job_execution_id::text = ANY(:executions)")
    return " OR ".join(f"({p})" for p in parts) or None


def _params(scope: dict) -> dict:
    return {"rids": scope["rids"], "eid": scope["engagement"], "instances": scope["instances"],
            "executions": scope["executions"]}


def row_counts(db: Session, scope: dict) -> dict[str, int]:
    """{table: rows} that the deletion removes, every table with any."""
    out = {}
    for table, cols in sorted(_columns(db).items()):
        where = _where(table, cols, scope)
        if where:
            n = db.execute(text(f'SELECT count(*) FROM "{table}" WHERE {where}'), _params(scope)).scalar()
            if n:
                out[table] = n
    return out


# ---------------------------------------------------------------- the checkout and the folders

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _inside(path: Path, folder: Path) -> bool:
    try:
        return Path(os.path.normcase(os.path.abspath(path))).is_relative_to(os.path.normcase(os.path.abspath(folder)))
    except ValueError:
        return False


def _experiment_folders(engagement_id: str, slug: str) -> list[Path]:
    """The engagement's experiments of this repository (experiment.yaml, or a generation's, names it)."""
    home = settings.runs_path / engagement_id / "experiments"
    out = []
    for folder in sorted(p for p in home.iterdir() if p.is_dir()) if home.exists() else []:
        for config in [folder / "experiment.yaml", *sorted(folder.glob("generation-*/experiment.yaml"))]:
            try:
                if config.exists() and (yaml.safe_load(config.read_text(encoding="utf-8")) or {}).get("repository") == slug:
                    out.append(folder)
                    break
            except (OSError, yaml.YAMLError):
                continue
    return out


def _recorded_branches(db: Session, repo: models.Repository) -> dict[str, str]:
    """{branch: where it is recorded} for every branch the platform created in this repository's checkout."""
    from app.engine import convert
    from app.experiment.prepare import copilot_runs

    out: dict[str, str] = {}
    for rec in convert.records(repo.engagement_id, repo.slug):
        out[rec["branch"]] = f"conversion {rec['number']}"
    for (branch,) in db.execute(text("SELECT branch FROM conversion_plans WHERE repository_id = :r"), {"r": repo.id}):
        out.setdefault(branch, "package-step plan")
    for (branch,) in db.execute(text("SELECT branch FROM engine_runs WHERE repository_id = :r AND branch IS NOT NULL"),
                                {"r": repo.id}):
        out.setdefault(branch, "engine run")
    for folder in _experiment_folders(repo.engagement_id, repo.slug):
        for config in [folder / "experiment.yaml", *sorted(folder.glob("generation-*/experiment.yaml"))]:
            if config.exists():
                try:
                    for r in copilot_runs(yaml.safe_load(config.read_text(encoding="utf-8")) or {}):
                        out.setdefault(r["branch"], f"experiment {folder.name}")
                except (KeyError, TypeError, ValueError, yaml.YAMLError):
                    continue
    return out


def _worktrees(checkout: Path) -> list[dict]:
    """[{path, branch}] of the checkout's linked worktrees (its own folder excluded)."""
    done = _git(checkout, "worktree", "list", "--porcelain")
    if done.returncode != 0:
        return []
    out, current = [], {}
    for line in done.stdout.splitlines() + [""]:
        if not line:
            if current:
                out.append(current)
            current = {}
        elif line.startswith("worktree "):
            current = {"path": line[len("worktree "):], "branch": None}
        elif line.startswith("branch refs/heads/"):
            current["branch"] = line[len("branch refs/heads/"):]
    return [w for w in out[1:]]


def _sharing(db: Session, repo: models.Repository, deleting: set) -> list[models.Repository]:
    """Other registrations, not being deleted, of this same checkout (the same git directory). Refused since
    release 2, but an installation upgraded from release 1 may have them (CLAUDE.md rule 15)."""
    from app.repositories.service import git_common_dir

    mine = git_common_dir(Path(repo.local_path))
    if mine is None:
        return []
    out = []
    for other in db.query(models.Repository).filter(models.Repository.id.notin_(deleting)):
        theirs = git_common_dir(Path(other.local_path)) if (Path(other.local_path) / ".git").exists() else None
        if theirs and theirs.lower() == mine.lower():
            out.append(other)
    return out


def _checkout_plan(db: Session, repo: models.Repository, scope_folder: Path, deleting: set) -> dict:
    """For one repository: the worktrees to remove, the branches to delete (and the recorded ones kept, why), and the
    run conversions whose agent work lives only on their branch. A branch another registration of the same checkout
    also records is kept: it may be that registration's work."""
    from app.engine import convert

    checkout = Path(repo.local_path)
    if repo.source_type == "git_clone":
        stays = (f"The clone at {checkout} stays where it is. The platform cloned it from {repo.clone_url}, but it is "
                 "your copy of the repository: only the worktrees and conversion branches the platform made in it go.")
    else:
        stays = (f"Your checkout at {checkout} stays where it is: only the worktrees and conversion branches the "
                 "platform made in it go.")
    if not (checkout / ".git").exists():
        return {"checkout": str(checkout), "stays": stays, "available": False, "worktrees": [], "branches": [],
                "kept": [], "run": []}
    worktrees = [w for w in _worktrees(checkout) if _inside(Path(w["path"]), scope_folder)]
    remaining = {w["branch"] for w in _worktrees(checkout) if not _inside(Path(w["path"]), scope_folder)}
    head = _git(checkout, "symbolic-ref", "--short", "-q", "HEAD").stdout.strip()
    remaining.add(head)
    existing = set(_git(checkout, "for-each-ref", "refs/heads", "--format=%(refname:short)").stdout.split())
    recorded = _recorded_branches(db, repo)
    shared = {}
    for other in _sharing(db, repo, deleting):
        for name in _recorded_branches(db, other):
            shared.setdefault(name, f"also recorded by {other.engagement_id}/{other.slug}, registered on the same checkout")
    others = sorted(existing - set(recorded))
    branches, kept = [], []
    for name, source in sorted(recorded.items()):
        if name not in existing:
            continue
        if name in remaining:
            kept.append({"branch": name, "source": source, "why": "checked out outside the platform's folders"})
            continue
        if name in shared:
            kept.append({"branch": name, "source": source, "why": shared[name]})
            continue
        only_here = _git(checkout, "rev-list", "--count", name, "--not", *others).stdout.strip() if others else ""
        branches.append({"branch": name, "source": source, "commits_only_here": int(only_here or 0)})
    run = []
    for rec in convert.records(repo.engagement_id, repo.slug):
        if rec["branch"] in existing:
            beyond = int(_git(checkout, "rev-list", "--count", f"{rec['head']}..{rec['branch']}").stdout.strip() or 0)
            if beyond:
                run.append({"repository": repo.slug, "number": rec["number"], "branch": rec["branch"],
                            "agent_commits": beyond})
    return {"checkout": str(checkout), "stays": stays, "available": True, "worktrees": worktrees,
            "branches": branches, "kept": kept, "run": run}


def _folder_facts(path: Path) -> dict:
    files = size = 0
    for root, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))
                   and not (hasattr(os.path, "isjunction") and os.path.isjunction(os.path.join(root, d)))]
        for n in names:
            files += 1
            try:
                size += os.path.getsize(os.path.join(root, n))
            except OSError:
                pass
    return {"path": str(path), "files": files, "bytes": size}


def remove_tree(path: Path) -> None:
    """Removes a folder without ever following a junction or a symbolic link: a conversion's worktree links the
    folders beside the client's checkout (siblings.link), and their contents are not the platform's to delete."""
    if not os.path.lexists(path):
        return
    if os.path.islink(path) or (hasattr(os.path, "isjunction") and os.path.isjunction(path)):
        os.rmdir(path) if os.path.isdir(path) else os.unlink(path)
        return
    for entry in os.scandir(path):
        link = entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction())
        if link:
            os.rmdir(entry.path) if entry.is_dir() else os.unlink(entry.path)
        elif entry.is_dir(follow_symlinks=False):
            remove_tree(Path(entry.path))
        else:
            try:
                os.unlink(entry.path)
            except PermissionError:
                os.chmod(entry.path, stat.S_IWRITE)
                os.unlink(entry.path)
    os.rmdir(path)


# ---------------------------------------------------------------- the plan, shown before anything goes

def _running(db: Session, scope: dict) -> list[dict]:
    rows = db.execute(text("""SELECT e.id, i.job_name, e.batch_status, e.created_at FROM wf_job_executions e
                              JOIN wf_job_instances i ON i.id = e.job_instance_id
                              WHERE e.id::text = ANY(:x) AND e.batch_status IN ('STARTING', 'STARTED')"""),
                      {"x": scope["executions"]}).all()
    return [{"job": job, "execution": str(eid), "status": status, "since": created.isoformat()}
            for eid, job, status, created in rows]


def repository_plan(db: Session, repo: models.Repository) -> dict:
    engagement = db.get(models.Engagement, repo.engagement_id)
    scope = _scope(db, engagement, [repo], whole=False)
    folder = settings.runs_path / repo.engagement_id / repo.slug
    folders = [f for f in [folder, *_experiment_folders(repo.engagement_id, repo.slug)] if f.exists()]
    return {"kind": "repository", "engagement": repo.engagement_id, "repository": repo.slug, "repository_id": str(repo.id),
            "name": repo.name, "confirm": repo.name, "rows": row_counts(db, scope),
            "folders": [_folder_facts(f) for f in folders], "checkouts": [_checkout_plan(db, repo, folder, {repo.id})],
            "running": _running(db, scope), "_scope": scope, "_folders": [str(f) for f in folders],
            "kept_shared": "the catalog, the package lookup cache, every other repository and engagement",
            "estate_note": "the engagement's estate view still counts this repository until the estate is consolidated again"}


def engagement_plan(db: Session, engagement: models.Engagement) -> dict:
    repositories = db.query(models.Repository).filter_by(engagement_id=engagement.id).order_by(models.Repository.slug).all()
    scope = _scope(db, engagement, repositories, whole=True)
    folder = settings.runs_path / engagement.id
    return {"kind": "engagement", "engagement": engagement.id, "name": engagement.client_name,
            "confirm": engagement.client_name, "repositories": [r.slug for r in repositories],
            "rows": row_counts(db, scope), "folders": [_folder_facts(folder)] if folder.exists() else [],
            "checkouts": [_checkout_plan(db, r, folder, {x.id for x in repositories}) for r in repositories], "running": _running(db, scope),
            "_scope": scope, "_folders": [str(folder)] if folder.exists() else [],
            "kept_shared": "the catalog, the package lookup cache, every other engagement"}


def public(plan: dict) -> dict:
    """The plan as shown: without its internal scope."""
    return {k: v for k, v in plan.items() if not k.startswith("_")}


# ---------------------------------------------------------------- the deletion

def _remove_files(plan: dict) -> dict:
    """The checkout's worktrees and branches, then the folders. Raises DeletionIncomplete, having removed what it
    could, when something is held open."""
    problems, removed_worktrees, removed_branches = [], [], []
    for c in plan["checkouts"]:
        if not c["available"]:
            continue
        checkout = Path(c["checkout"])
        for w in c["worktrees"]:
            try:
                remove_tree(Path(w["path"]))
                removed_worktrees.append(w["path"])
            except OSError as e:
                problems.append(f"worktree {w['path']}: {e.strerror or e}")
        _git(checkout, "worktree", "prune")
        for b in c["branches"]:
            done = _git(checkout, "branch", "-D", b["branch"])
            if done.returncode == 0:
                removed_branches.append(f"{Path(c['checkout']).name}:{b['branch']}")
            else:
                problems.append(f"branch {b['branch']}: {(done.stderr or done.stdout).strip()[:300]}")
    for f in plan["_folders"]:
        try:
            remove_tree(Path(f))
        except OSError as e:
            problems.append(f"folder {f}: {e.strerror or e} ({getattr(e, 'filename', '')})")
    if problems:
        raise DeletionIncomplete("Some files could not be removed, so nothing was deleted from the database. Close "
                                 "any program holding them (Visual Studio, an editor, a terminal inside the folder), "
                                 "then delete again:\n  " + "\n  ".join(problems))
    return {"worktrees": removed_worktrees, "branches": removed_branches, "folders": plan["_folders"]}


def _delete_rows(db: Session, plan: dict) -> None:
    scope, p = plan["_scope"], _params(plan["_scope"])
    db.execute(text("DELETE FROM wf_artifacts WHERE job_execution_id::text = ANY(:executions)"), p)
    db.execute(text("DELETE FROM wf_step_executions WHERE job_execution_id::text = ANY(:executions)"), p)
    db.execute(text("DELETE FROM wf_job_executions WHERE id::text = ANY(:executions)"), p)
    db.execute(text("DELETE FROM wf_job_instances WHERE id::text = ANY(:instances)"), p)
    db.execute(text("DELETE FROM engine_runs WHERE repository_id::text = ANY(:rids)"), p)
    db.execute(text("DELETE FROM integration_edges WHERE caller_repository_id::text = ANY(:rids) "
                    "OR callee_repository_id::text = ANY(:rids)"), p)
    db.execute(text("DELETE FROM integration_entry_points WHERE repository_id::text = ANY(:rids)"), p)
    db.execute(text("DELETE FROM repositories WHERE id::text = ANY(:rids)"), p)      # and everything that cascades
    if scope["whole"]:
        for table in ENGAGEMENT_NO_CASCADE:
            db.execute(text(f'DELETE FROM "{table}" WHERE engagement_id = :eid'), p)
        db.execute(text("DELETE FROM engagements WHERE id = :eid"), p)               # and everything that cascades
    # Stored result contents (app.results) no artifact refers to any more; one another repository shares stays.
    db.execute(text("DELETE FROM result_contents c WHERE NOT EXISTS "
                    "(SELECT 1 FROM result_artifacts a WHERE a.checksum = c.checksum)"))
    left = row_counts(db, scope)
    if left:
        raise RuntimeError(f"rows would be left behind, so nothing was deleted: {left}")


def delete(db: Session, plan: dict, typed: str, via: str) -> dict:
    """Deletes what `plan` describes, after checking the typed name and that no job of it is running. Returns the
    audit summary."""
    if typed.strip() != plan["confirm"]:
        raise DeletionRefused(f"Not deleted: type the {plan['kind']}'s name exactly, \"{plan['confirm']}\", to confirm.")
    running = _running(db, plan["_scope"])
    if running:
        raise DeletionRefused(f"Not deleted: {len(running)} job(s) of this {plan['kind']} are running "
                              f"({', '.join(r['job'] for r in running)}). Wait for them to end, then delete.")
    files = _remove_files(plan)
    summary = {"rows": plan["rows"], "folders": [f["path"] for f in plan["folders"]], "worktrees": files["worktrees"],
               "branches": files["branches"], "run_conversions_lost": [r for c in plan["checkouts"] for r in c["run"]],
               "repositories": plan.get("repositories") or [plan.get("repository")]}
    try:
        _delete_rows(db, plan)
        db.add(models.DeletionAudit(
            deleted_by=f"{getpass.getuser()}@{socket.gethostname()}", via=via, kind=plan["kind"],
            engagement_id=plan["engagement"], repository_slug=plan.get("repository"), name=plan["name"],
            summary=json.loads(json.dumps(summary, default=str))))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {**summary, "deleted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
