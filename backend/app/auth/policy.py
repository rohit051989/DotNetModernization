"""Who may take each action, enforced in the backend for every API call (app.auth.http), never only in the UI.

Two roles:
- admin: everything, including the catalog, users, engagements, decisions and confirmations;
- developer: registers repositories, and acts on the ones they own.

A repository's owner (the developer who registered it) may rescan it, edit it, prepare and verify its conversions,
resume or stop its jobs, and delete it (restoring a soft-deleted one is an admin's, CLAUDE.md rule 7). Everyone else sees it read-only. A repository with no owner yet (registered
before sign-in existed) is acted on only by an admin, until one assigns an owner.

Reading is open to everyone signed in. Every change not listed below is for admins only, so a new route is safe by
default: it must be listed here to be open to developers.
"""
import uuid

from sqlalchemy.orm import Session

from app import models
from app.auth import actor as actors

ANY, OWNER, EXECUTION_OWNER = "any", "owner", "execution_owner"

# (method, route path) -> rule, for changes open beyond admins.
RULES: dict[tuple[str, str], str] = {
    # The person's own session and password.
    ("POST", "/api/auth/sign-out"): ANY,
    ("POST", "/api/auth/password"): ANY,
    # Read-only checks and the person's own editor.
    ("POST", "/api/engagements/{engagement_id}/repositories/inspect-path"): ANY,
    ("POST", "/api/engagements/{engagement_id}/repositories/inspect-url"): ANY,
    ("POST", "/api/workflow/jobs/validate"): ANY,
    ("POST", "/api/workflow/step-policies/validate"): ANY,
    ("POST", "/api/engagements/{engagement_id}/step-policies/validate"): ANY,
    ("POST", "/api/editors/visual-studio/open"): ANY,
    # Registering a repository: anyone signed in, who then owns it.
    ("POST", "/api/engagements/{engagement_id}/repositories/register"): ANY,
    # Each person's own clone of a repository, on their own machine: theirs to record or forget, whoever owns it.
    ("POST", "/api/repositories/{repository_id}/clone"): ANY,
    ("DELETE", "/api/repositories/{repository_id}/clone"): ANY,
    # The owner's repository.
    ("PUT", "/api/repositories/{repository_id}"): OWNER,
    ("DELETE", "/api/repositories/{repository_id}"): OWNER,
    ("POST", "/api/repositories/{repository_id}/rescan"): OWNER,
    ("POST", "/api/repositories/{repository_id}/verify-path"): OWNER,
    ("POST", "/api/repositories/{repository_id}/deletion"): OWNER,
    ("POST", "/api/repositories/{repository_id}/conversions"): OWNER,
    ("POST", "/api/repositories/{repository_id}/conversions/{number}/verify"): OWNER,
    # A job on the owner's repository.
    ("POST", "/api/workflow/executions/{execution_id}/resume"): EXECUTION_OWNER,
    ("POST", "/api/workflow/executions/{execution_id}/stop"): EXECUTION_OWNER,
}

READ_METHODS = ("GET", "HEAD", "OPTIONS")

# Actions on the repository's own folder and run output, which exist only on the machine it was registered on.
ON_ITS_MACHINE = {
    ("POST", "/api/repositories/{repository_id}/rescan"),
    ("POST", "/api/repositories/{repository_id}/verify-path"),
    ("POST", "/api/repositories/{repository_id}/deletion"),
    ("POST", "/api/repositories/{repository_id}/conversions"),
    ("POST", "/api/repositories/{repository_id}/conversions/{number}/verify"),
}


def owner_name(db: Session, repository: models.Repository) -> str | None:
    if repository.owner_user_id is None:
        return None
    owner = db.get(models.User, repository.owner_user_id)
    return owner.name if owner else None


def repository_refusal(db: Session, actor: actors.Actor, repository: models.Repository) -> str | None:
    """Why this person may not act on this repository, or None."""
    if actor.is_admin:
        return None
    if repository.owner_user_id is None:
        return ("This repository has no owner yet (it was registered before sign-in existed): only an admin may act on "
                "it until an admin assigns one.")
    if repository.owner_user_id == actor.user_id:
        return None
    return f"Only this repository's owner, {owner_name(db, repository) or 'its owner'}, or an admin may do this."


def machine_refusal(repository: models.Repository, host: str | None) -> str | None:
    """Why an action on the repository's folder cannot be taken from this machine, or None."""
    from app.auth import machine

    if repository.registered_host and host and not machine.same(repository.registered_host, host):
        return (f"This repository was registered on {repository.registered_host}: its folder and run output are on that "
                "machine, so do this from the platform there.")
    return None


def _execution_repository(db: Session, execution_id: str) -> models.Repository | None:
    try:
        execution = db.get(models.WfJobExecution, uuid.UUID(str(execution_id)))
    except ValueError:
        return None
    if execution is None:
        return None
    instance = db.get(models.WfJobInstance, execution.job_instance_id)
    repository_id = (instance.parameters or {}).get("repository_id") if instance else None
    if not repository_id:
        return None
    try:
        return db.get(models.Repository, uuid.UUID(str(repository_id)))
    except ValueError:
        return None


def refusal(db: Session, actor: actors.Actor, method: str, route_path: str, path_params: dict) -> str | None:
    """Why this person may not make this call, or None."""
    if method in READ_METHODS:
        return None
    rule = RULES.get((method, route_path))
    if rule == OWNER:
        try:
            repository = db.get(models.Repository, uuid.UUID(str(path_params.get("repository_id"))))
        except ValueError:
            return None                       # the route answers 404/422 itself
        if repository is None:
            return None
        if (method, route_path) in ON_ITS_MACHINE and (why := machine_refusal(repository, actor.hostname)):
            return why
        return repository_refusal(db, actor, repository)
    if actor.is_admin or rule == ANY:
        return None
    if rule == EXECUTION_OWNER:
        repository = _execution_repository(db, path_params.get("execution_id"))
        if repository is None:
            return "Only an admin may act on a job that is not about one repository."
        return repository_refusal(db, actor, repository)
    return "Only an admin may do this: a developer registers repositories and acts on the ones they own."
