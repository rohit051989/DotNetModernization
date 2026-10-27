"""Each person's own clone of a repository (docs/VDI-SETUP.md, "Your own clone of a repository").

File locations are stored relative to the repository. Each person records where their own clone is, on their own
machine; the owner's is the folder the repository was registered from. An editor link joins the viewer's clone with
the file's relative path, so the owner and a viewer each open the same file from their own clone.

A viewer records their clone from the repository's page. The folder must be the top of a git clone whose remote is the
repository's own (its clone URL, compared as 15-REPOSITORY-INGEST-UI.md Part C normalises URLs: the same repository
cloned over https or ssh is the same); a clone of another repository is refused.
"""
import os
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.auth import activity, machine
from app.auth import actor as actors
from app.auth.service import Refused
from app.config import settings
from app.steps.repository_ingest import normalize_clone_url, run_git


def _row(db: Session, repository: models.Repository, user_id, host: str) -> models.RepositoryClone | None:
    return (db.query(models.RepositoryClone)
            .filter(models.RepositoryClone.repository_id == repository.id, models.RepositoryClone.user_id == user_id,
                    func.lower(models.RepositoryClone.hostname) == host.strip().lower())
            .one_or_none())


def path_for(db: Session, repository: models.Repository, person: actors.Actor | None, host: str) -> str | None:
    """The folder of this person's own clone on this machine, or None when they have recorded none. On the machine a
    repository was registered on (or for one registered before sign-in existed, which has none), its registered
    folder is there."""
    if person is not None and person.user_id is not None:
        row = _row(db, repository, person.user_id, host)
        if row is not None:
            return row.local_path
    if not repository.registered_host or machine.same(repository.registered_host, host):
        return repository.local_path
    return None


def remote_url(repository: models.Repository) -> str | None:
    """The URL a clone of this repository has as its remote: its clone URL, else the one found in its folder."""
    return repository.clone_url or repository.detected_clone_url


def clone_command(repository: models.Repository) -> str | None:
    """The command that makes a clone of it on this machine, under REPOS_DIR; None without a URL to clone from."""
    url = remote_url(repository)
    if not url:
        return None
    try:
        base = settings.repos_path
    except ValueError:
        base = None
    target = base / repository.root_folder_name if base else Path(repository.root_folder_name)
    return f'git clone -c core.longpaths=true {url} "{target}"'


def check(repository: models.Repository, folder: str) -> str:
    """The folder, normalised, when it is the top of a clone of this repository; else Refused, saying why."""
    raw = (folder or "").strip().strip('"')
    if not raw or not os.path.isabs(raw):
        raise Refused("Give the full path of your clone's folder, such as C:\\MP\\repos\\OrderService.", "INVALID_PATH")
    path = Path(raw)
    if not path.is_dir():
        raise Refused(f"{raw} is not a folder on this machine.", "NOT_FOUND")
    expected = remote_url(repository)
    if not expected:
        raise Refused(f"{repository.name} has no remote URL, so a clone of it cannot be checked: its owner can set its "
                      "clone URL (Edit, on its page).", "NO_REMOTE")
    top = run_git(path, "rev-parse", "--show-toplevel")
    if top is None:
        raise Refused(f"{raw} is not a git clone (git finds no repository there).", "NOT_A_CLONE")
    # Resolved, so a short (8.3) name, a different case or a junction names the same folder as git's own.
    path = path.resolve()
    if os.path.normcase(str(Path(top).resolve())) != os.path.normcase(str(path)):
        raise Refused(f"{raw} is inside the clone at {os.path.normpath(top)}: give that folder, the top of the clone.",
                      "NOT_TOP")
    remotes = (run_git(path, "remote", "-v") or "").split()
    urls = {normalize_clone_url(word) for word in remotes if "/" in word or ":" in word}
    wanted = normalize_clone_url(expected)
    if wanted not in urls:
        found = ", ".join(sorted(urls)) or "no remote"
        raise Refused(f"{raw} is a clone of {found}, not of {repository.name} ({wanted}): not recorded.",
                      "DIFFERENT_REPOSITORY")
    return str(path)


def record(db: Session, repository: models.Repository, person: actors.Actor, host: str, folder: str) -> models.RepositoryClone:
    """Records (or replaces) the person's clone on this machine, after `check`. The caller commits."""
    if person.user_id is None:
        raise Refused("Sign in to record your clone.", "NOT_ALLOWED")
    path = check(repository, folder)
    row = _row(db, repository, person.user_id, host)
    if row is None:
        row = models.RepositoryClone(repository_id=repository.id, user_id=person.user_id, hostname=host)
        db.add(row)
    row.local_path = path
    row.recorded_at = func.now()
    db.flush()
    activity.record(db, "record_clone", "repository", str(repository.id), f"Recorded their clone at {path} on {host}",
                    actor=person)
    return row


def forget(db: Session, repository: models.Repository, person: actors.Actor, host: str) -> bool:
    row = _row(db, repository, person.user_id, host) if person.user_id else None
    if row is None:
        return False
    db.delete(row)
    db.flush()
    activity.record(db, "forget_clone", "repository", str(repository.id), f"Forgot their clone on {host}", actor=person)
    return True


def record_registered(db: Session, repository: models.Repository) -> None:
    """At registration: the owner's clone is the folder it was registered from."""
    if repository.owner_user_id is None or not repository.registered_host:
        return
    row = _row(db, repository, repository.owner_user_id, repository.registered_host)
    if row is None:
        db.add(models.RepositoryClone(repository_id=repository.id, user_id=repository.owner_user_id,
                                      hostname=repository.registered_host, local_path=repository.local_path))
    else:
        row.local_path = repository.local_path
    db.flush()
