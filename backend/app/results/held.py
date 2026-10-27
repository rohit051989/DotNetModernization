"""What is only on the machine a repository was scanned on (app.results): logs, timing profiles, evidence files, raw
outputs no view needs, the repository's own files. Someone on another machine is told where it is, "on <owner>'s
machine (<host>)", instead of being given a link that cannot work."""
import uuid

from sqlalchemy.orm import Session

from app import models
from app.auth import machine

LOCAL_ONLY = "LOCAL_ONLY"


def owner_name(db: Session, repository: models.Repository | None) -> str | None:
    if repository is None or repository.owner_user_id is None:
        return None
    user = db.get(models.User, repository.owner_user_id)
    return user.name if user else None


def where(db: Session, repository: models.Repository | None, host: str | None) -> str:
    """"on Ann's machine (PC-17)", "on PC-17", or "on another machine" when nothing records which."""
    owner = owner_name(db, repository)
    if owner and host:
        return f"on {owner}'s machine ({host})"
    if host:
        return f"on {host}"
    if owner:
        return f"on {owner}'s machine"
    return "on another machine"


def elsewhere(host: str | None) -> bool:
    """True when `host` names another machine than this one."""
    return bool(host) and not machine.same(host, machine.hostname())


def execution_host(db: Session, job_execution_id: uuid.UUID) -> str | None:
    execution = db.get(models.WfJobExecution, job_execution_id)
    return execution.queued_by_host if execution else None


def repository_of(db: Session, repository_id) -> models.Repository | None:
    if not repository_id:
        return None
    try:
        return db.get(models.Repository, uuid.UUID(str(repository_id)))
    except ValueError:
        return None


def artifact_where(db: Session, artifact: models.WfArtifact) -> tuple[str | None, str]:
    """The machine an artifact's file is on, and how to say so."""
    from app.results import store

    repository_id, _ = store.scope(db, artifact.job_execution_id)
    repository = repository_of(db, repository_id)
    host = execution_host(db, artifact.job_execution_id) or (repository.registered_host if repository else None)
    return host, where(db, repository, host)


def repository_where(db: Session, repository: models.Repository) -> str:
    return where(db, repository, repository.registered_host)
