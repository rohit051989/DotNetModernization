"""Repository registration business logic — see 15-REPOSITORY-INGEST-UI.md
Parts C, D and E. Callers (routers) own the transaction: this module flushes
but never commits.
"""

import datetime
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.repositories import git_source
from app.repositories.schemas import (
    DuplicateConflict,
    InspectPathResponse,
    InspectUrlResponse,
    RegisterGitCloneRequest,
    RegisterLocalPathRequest,
    RepositoryUpdate,
)
from app.steps import repository_ingest

MAX_SCAN_ENTRIES = 20_000

_SYSTEM_LOCATIONS = {
    r"c:\windows",
    r"c:\program files",
    r"c:\program files (x86)",
    r"c:\programdata",
}
_DRIVE_ROOT_RE = re.compile(r"^[a-zA-Z]:\\?$")
# SSH remotes, in git's two spellings: scp-like git@host:org/repo.git, and ssh://[user@]host[:port]/org/repo.git.
_SSH_CLONE_RE = re.compile(r"^git@[^:/]+:.+$")
_SSH_URL_CLONE_RE = re.compile(r"^ssh://(?:[^@/:]+@)?[^@/:]+(?::\d+)?/.+$")
_ACCEPTED_FORMS = "an https URL, git@host:org/repo.git or ssh://host/org/repo.git"
_MATCH_LABELS = {"clone_url": "clone URL", "root_folder_name": "root folder name", "local_path": "local path"}


class RegistrationError(Exception):
    """Carries errors in this API's shared shape (see app/errors.py) plus the
    status code the router should use — 422 for validation, 409 for
    duplicate/nesting conflicts."""

    def __init__(self, status_code: int, errors: list[dict]):
        super().__init__("; ".join(e["message"] for e in errors))
        self.status_code = status_code
        self.errors = errors


# ---------- Normalisation & derivation ----------


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "repository"


def normalize_local_path(raw_path: str) -> str:
    """Resolve to absolute, normalise separators, uppercase the Windows drive
    letter consistently, strip trailing separator — 15-REPOSITORY-INGEST-UI.md
    Part C. Case elsewhere in the path is preserved, exactly as specified."""
    text = str(Path(raw_path).resolve())
    if re.match(r"^[a-zA-Z]:", text):
        text = text[0].upper() + text[1:]
    return text.rstrip("\\/")


def derive_provider(clone_url: str | None) -> str | None:
    """Host-derived provider for a clone URL, per Part C. Null when there is
    no clone URL to derive one from — a folder never under source control."""
    if not clone_url:
        return None
    host = urlparse(repository_ingest.normalize_clone_url(clone_url)).hostname or ""
    if "github" in host:
        return "github"
    if "bitbucket" in host:
        return "bitbucket"
    if "dev.azure.com" in host or "visualstudio.com" in host:
        return "azure_devops"
    if "gitlab" in host:
        return "gitlab"
    return "other"


def _looks_like_network_path(path: Path) -> bool:
    return str(path).startswith("\\\\")


def _has_any_file(path: Path) -> bool:
    for _root, _dirs, files in os.walk(path):
        if files:
            return True
    return False


# ---------- Part E validation ----------


def validate_local_path_for_registration(raw_path: str) -> list[dict]:
    """Part E rules for `local_path`. Returns a list of problems (empty if
    none) in this API's shared error shape."""
    raw = raw_path.strip()
    path = Path(raw)

    if not path.is_absolute():
        return [{"field": "local_path", "message": f"'{raw}' is not an absolute path.", "code": "RELATIVE_PATH"}]

    normalised_for_check = raw.rstrip("\\/").lower()
    if _DRIVE_ROOT_RE.match(raw) or normalised_for_check in _SYSTEM_LOCATIONS:
        return [
            {
                "field": "local_path",
                "message": f"'{raw}' is a system location and cannot be registered.",
                "code": "SYSTEM_LOCATION",
            }
        ]

    if not path.exists() or not path.is_dir():
        return [
            {
                "field": "local_path",
                "message": f"'{raw}' does not exist or is not a directory.",
                "code": "PATH_NOT_FOUND",
            }
        ]

    if not _has_any_file(path):
        return [{"field": "local_path", "message": f"'{raw}' contains no files.", "code": "EMPTY_FOLDER"}]

    return []


def validate_clone_url(raw_url: str, allow_file: bool = False) -> list[dict]:
    """Part E rules for `clone_url`: must be https, git@host:org/repo or
    ssh://host/org/repo, and must not embed credentials. `allow_file`: a
    repository registered by URL may also come from a folder or a share, as
    file:///D:/mirror/repo.git."""
    url = raw_url.strip()
    parsed = urlparse(url)
    if allow_file and parsed.scheme == "file" and len(url) > len("file:///"):
        return []
    is_https = parsed.scheme == "https" and bool(parsed.netloc)
    is_ssh = bool(_SSH_CLONE_RE.match(url) or _SSH_URL_CLONE_RE.match(url))

    if parsed.scheme == "ssh" and parsed.password:
        return [
            {
                "field": "clone_url",
                "message": "Embedded credentials are not allowed in a clone URL. SSH authenticates with your SSH key.",
                "code": "EMBEDDED_CREDENTIALS",
            }
        ]

    if not (is_https or is_ssh):
        looks_local = bool(re.match(r"^([a-zA-Z]:[\\/]|\\\\|/|file:)", url))
        message = (
            f"'{url}' is a local folder, not a URL: enter the repository's canonical URL ({_ACCEPTED_FORMS})."
            if looks_local else f"'{url}' must be {_ACCEPTED_FORMS}."
        )
        return [{"field": "clone_url", "message": message, "code": "INVALID_CLONE_URL"}]

    if is_https and (parsed.username or parsed.password):
        return [
            {
                "field": "clone_url",
                "message": (
                    "Embedded credentials are not allowed in a clone URL. "
                    "Use environment variables on the host instead."
                ),
                "code": "EMBEDDED_CREDENTIALS",
            }
        ]

    return []


# ---------- Duplicate detection & nesting guard ----------


def find_duplicate_conflict(
    db: Session,
    engagement_id: str,
    clone_url_normalised: str | None,
    root_folder_name: str,
    local_path_normalised: str,
    exclude_id: uuid.UUID | None = None,
) -> tuple[str, models.Repository] | None:
    """Checks the three partial-unique-index conditions from Part C, in the
    order clone URL (canonical identity) → root folder name → local path.
    Returns (matched_on, existing_row) for the first hit, or None."""
    base = db.query(models.Repository).filter(
        models.Repository.engagement_id == engagement_id,
        models.Repository.deleted_at.is_(None),
    )
    if exclude_id is not None:
        base = base.filter(models.Repository.id != exclude_id)

    if clone_url_normalised:
        existing = base.filter(models.Repository.clone_url_normalised == clone_url_normalised).first()
        if existing is not None:
            return "clone_url", existing

    existing = base.filter(models.Repository.root_folder_name == root_folder_name).first()
    if existing is not None:
        return "root_folder_name", existing

    existing = base.filter(models.Repository.local_path_normalised == local_path_normalised).first()
    if existing is not None:
        return "local_path", existing

    return None


def duplicate_conflict_message(db: Session, engagement_id: str, existing: models.Repository, matched_on: str) -> str:
    engagement = db.get(models.Engagement, engagement_id)
    client_name = engagement.client_name if engagement is not None else engagement_id
    return (
        f'This repository is already registered for {client_name} as "{existing.slug}" '
        f"(matched on {_MATCH_LABELS[matched_on]}). Use Rescan to re-run discovery, or "
        "delete the existing registration first."
    )


def find_nesting_conflict(
    db: Session, engagement_id: str, local_path_normalised: str, exclude_id: uuid.UUID | None = None
) -> models.Repository | None:
    """Rejects registration when the candidate path is a parent or descendant
    of an already-registered, non-deleted path in the same engagement."""
    candidates = db.query(models.Repository).filter(
        models.Repository.engagement_id == engagement_id,
        models.Repository.deleted_at.is_(None),
    )
    if exclude_id is not None:
        candidates = candidates.filter(models.Repository.id != exclude_id)

    candidate = local_path_normalised.rstrip("\\/").lower()
    for repo in candidates:
        existing = repo.local_path_normalised.rstrip("\\/").lower()
        if existing == candidate:
            continue  # exact match is the local_path duplicate check, not nesting
        if candidate.startswith(existing + "\\") or existing.startswith(candidate + "\\"):
            return repo
    return None


def git_common_dir(path: Path) -> str | None:
    """The git directory a checkout's branches live in: shared by a repository and every worktree of it. None for a
    folder that is not a git checkout."""
    common = repository_ingest.run_git(path, "rev-parse", "--git-common-dir")
    if not common:
        return None
    return normalize_local_path(str((path / common).resolve() if not Path(common).is_absolute() else Path(common)))


def find_checkout_in_other_engagement(db: Session, engagement_id: str, local_path: str) -> models.Repository | None:
    """A registration of the same checkout — the same folder, or any worktree sharing its git directory — in another
    engagement. A checkout serves one engagement: the platform creates its conversion and experiment branches, and
    the worktrees on them, in the checkout's git, under names (conversion/1, ...) that a second engagement would
    reuse."""
    path = Path(local_path)
    normalised = normalize_local_path(local_path).lower()
    common = git_common_dir(path) if (path / ".git").exists() else None
    others = db.query(models.Repository).filter(models.Repository.engagement_id != engagement_id,
                                                models.Repository.deleted_at.is_(None))
    for other in others:
        if other.local_path_normalised.lower() == normalised:
            return other
        if common and Path(other.local_path).exists() and (Path(other.local_path) / ".git").exists():
            theirs = git_common_dir(Path(other.local_path))
            if theirs and theirs.lower() == common.lower():
                return other
    return None


def checkout_in_other_engagement_message(other: models.Repository) -> str:
    return (f"This checkout is already registered in engagement '{other.engagement_id}' as \"{other.slug}\" "
            f"({other.local_path}). A checkout serves one engagement: the platform creates its conversion and "
            "experiment branches, and their worktrees, in the checkout's git, and a second engagement would reuse the "
            "same branch names. To use the repository here too, clone it again into another folder and register that "
            "folder.")


def _unique_slug(db: Session, engagement_id: str, base_slug: str) -> str:
    slug = base_slug
    suffix = 2
    while (
        db.query(models.Repository)
        .filter(
            models.Repository.engagement_id == engagement_id,
            models.Repository.slug == slug,
            models.Repository.deleted_at.is_(None),
        )
        .first()
        is not None
    ):
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    return slug


# ---------- Path inspection ----------


def _no_origin_message(path: Path) -> str:
    """Why a git repository has no origin URL to detect: no remote at all, or remotes under other names."""
    remotes = (repository_ingest.run_git(path, "remote") or "").split()
    if not remotes:
        return (
            "This repository has no git remote at all, so there is no clone URL to detect or verify against. "
            "Leave the clone URL empty, or enter the repository's canonical URL if it has one: it will be recorded "
            "unverified."
        )
    return (
        f"This repository has no remote named origin (it has {', '.join(remotes)}), so its clone URL is not "
        "detected. Enter the repository's canonical URL: it will be recorded unverified."
    )



def _scan_folder(path: Path) -> dict:
    """Bounded traversal for inspect-path: sampled file count/size estimates
    plus solution/project file counts, skipping the same directories step 1
    skips. Caps at MAX_SCAN_ENTRIES so a huge folder doesn't block the
    request — estimates, not analysis."""
    file_count = 0
    size_bytes = 0
    solution_count = 0
    project_count = 0
    capped = False

    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in repository_ingest.SKIP_DIR_NAMES]
        for filename in files:
            if file_count >= MAX_SCAN_ENTRIES:
                capped = True
                break
            file_path = Path(root) / filename
            try:
                size_bytes += file_path.stat().st_size
            except OSError:
                continue
            file_count += 1
            lower = filename.lower()
            if lower.endswith(".sln"):
                solution_count += 1
            elif lower.endswith(".csproj"):
                project_count += 1
        if capped:
            break

    return {
        "file_count": file_count,
        "size_bytes": size_bytes,
        "solution_count": solution_count,
        "project_count": project_count,
    }


def inspect_path(db: Session, engagement_id: str, raw_local_path: str) -> InspectPathResponse:
    path = Path(raw_local_path)
    exists = path.exists()
    is_directory = exists and path.is_dir()

    if not exists or not is_directory:
        return InspectPathResponse(
            exists=exists,
            is_directory=is_directory,
            root_folder_name=None,
            suggested_name=None,
            suggested_slug=None,
            has_git=False,
            source_control_status="NONE",
            detected_clone_url=None,
            detected_provider=None,
            detected_branch=None,
            detected_commit_sha=None,
            estimated_file_count=None,
            estimated_size_bytes=None,
            solution_files_found=None,
            project_files_found=None,
            duplicate_conflict=None,
            warnings=[],
        )

    root_folder_name = path.name
    has_git = (path / ".git").is_dir()
    detected_clone_url = None
    detected_branch = None
    detected_commit_sha = None
    if has_git:
        detected_clone_url = repository_ingest.run_git(path, "config", "--get", "remote.origin.url")
        detected_branch = repository_ingest.run_git(path, "rev-parse", "--abbrev-ref", "HEAD")
        detected_commit_sha = repository_ingest.run_git(path, "rev-parse", "HEAD")
    detected_provider = derive_provider(detected_clone_url) if detected_clone_url else None

    scan = _scan_folder(path)

    warnings: list[str] = []
    if not has_git:
        warnings.append("No .git directory found, so the clone URL cannot be verified.")
    elif detected_clone_url is None:
        warnings.append(_no_origin_message(path))
    elif validate_clone_url(detected_clone_url):
        warnings.append(
            f"The origin remote is {detected_clone_url}, which is not a URL the platform accepts: enter the "
            f"repository's canonical URL ({_ACCEPTED_FORMS})."
        )
    if scan["file_count"] == 0:
        warnings.append("Folder appears empty.")
    if scan["solution_count"] == 0 and scan["project_count"] == 0:
        warnings.append("No .sln or .csproj found — the folder may still be in scope.")
    if _looks_like_network_path(path):
        warnings.append("Path is on a network drive, which will make scanning slow.")
    elsewhere = find_checkout_in_other_engagement(db, engagement_id, raw_local_path)
    if elsewhere is not None:
        warnings.append(checkout_in_other_engagement_message(elsewhere))

    duplicate_conflict = None
    match = find_duplicate_conflict(
        db,
        engagement_id,
        clone_url_normalised=repository_ingest.normalize_clone_url(detected_clone_url)
        if detected_clone_url
        else None,
        root_folder_name=root_folder_name,
        local_path_normalised=normalize_local_path(raw_local_path),
    )
    if match is not None:
        matched_on, existing = match
        duplicate_conflict = DuplicateConflict(
            matched_on=matched_on,
            repository_id=str(existing.id),
            slug=existing.slug,
            message=duplicate_conflict_message(db, engagement_id, existing, matched_on),
        )

    return InspectPathResponse(
        exists=True,
        is_directory=True,
        root_folder_name=root_folder_name,
        suggested_name=root_folder_name,
        suggested_slug=slugify(root_folder_name),
        has_git=has_git,
        source_control_status="GIT" if has_git else "NONE",
        detected_clone_url=detected_clone_url,
        detected_provider=detected_provider,
        detected_branch=detected_branch,
        detected_commit_sha=detected_commit_sha,
        estimated_file_count=scan["file_count"],
        estimated_size_bytes=scan["size_bytes"],
        solution_files_found=scan["solution_count"],
        project_files_found=scan["project_count"],
        duplicate_conflict=duplicate_conflict,
        warnings=warnings,
    )


# ---------- Registration ----------


def register_local_path(
    db: Session, engagement: models.Engagement, payload: RegisterLocalPathRequest
) -> models.Repository:
    path = Path(payload.local_path)
    # Safe to check even before path validation — .is_dir() on a bad path
    # just returns False, it doesn't raise.
    has_git = (path / ".git").is_dir()
    clone_url_raw = (payload.clone_url or "").strip() or None

    problems = validate_local_path_for_registration(payload.local_path)
    if clone_url_raw:
        problems += validate_clone_url(clone_url_raw)
    # A repository with an origin remote needs its clone URL, to verify against it. One with no remote at all has
    # nothing to verify against: it registers without one (clone_url_verification not_applicable).
    has_origin = has_git and repository_ingest.run_git(path, "config", "--get", "remote.origin.url") is not None
    if has_origin and not clone_url_raw:
        problems.append(
            {
                "field": "clone_url",
                "message": (
                    "This repository has an origin remote: a clone URL is required so it can be "
                    "verified against it."
                ),
                "code": "CLONE_URL_REQUIRED_FOR_GIT",
            }
        )
    if problems:
        raise RegistrationError(422, problems)

    local_path_normalised = normalize_local_path(payload.local_path)
    clone_url_normalised = repository_ingest.normalize_clone_url(clone_url_raw) if clone_url_raw else None

    conflict = find_duplicate_conflict(
        db, engagement.id, clone_url_normalised, path.name, local_path_normalised
    )
    if conflict is not None:
        matched_on, existing = conflict
        raise RegistrationError(
            409,
            [
                {
                    "field": None,
                    "message": duplicate_conflict_message(db, engagement.id, existing, matched_on),
                    "code": f"DUPLICATE_{matched_on.upper()}",
                }
            ],
        )

    elsewhere = find_checkout_in_other_engagement(db, engagement.id, payload.local_path)
    if elsewhere is not None:
        raise RegistrationError(
            409,
            [{"field": "local_path", "message": checkout_in_other_engagement_message(elsewhere),
              "code": "CHECKOUT_IN_OTHER_ENGAGEMENT"}],
        )

    nesting_conflict = find_nesting_conflict(db, engagement.id, local_path_normalised)
    if nesting_conflict is not None:
        raise RegistrationError(
            409,
            [
                {
                    "field": "local_path",
                    "message": (
                        f"'{payload.local_path}' is a parent or descendant of already-registered "
                        f'repository "{nesting_conflict.slug}" ({nesting_conflict.local_path}). '
                        "Nested registrations double-count applications and are not allowed."
                    ),
                    "code": "NESTED_PATH",
                }
            ],
        )

    detected_clone_url = (
        repository_ingest.run_git(path, "config", "--get", "remote.origin.url") if has_git else None
    )
    if not has_git:
        # No .git at all: nothing to verify against. A URL may still have
        # been supplied (e.g. a repository being migrated into source
        # control) — record it, but there is no remote to check it against,
        # which is a distinct state from "verification was never
        # attempted because there's no URL at all".
        clone_url_verification = "unverifiable" if clone_url_raw else "not_applicable"
    elif detected_clone_url is None:
        # No origin remote: a URL given is recorded unverified; none given, there is nothing to verify.
        clone_url_verification = "unverifiable" if clone_url_raw else "not_applicable"
    elif repository_ingest.normalize_clone_url(detected_clone_url) == clone_url_normalised:
        clone_url_verification = "verified"
    else:
        clone_url_verification = "mismatch"

    now = datetime.datetime.now(datetime.timezone.utc)
    repo = models.Repository(
        id=uuid.uuid4(),
        engagement_id=engagement.id,
        name=payload.name or path.name,
        root_folder_name=path.name,
        slug=_unique_slug(db, engagement.id, slugify(path.name)),
        local_path=payload.local_path,
        local_path_normalised=local_path_normalised,
        clone_url=clone_url_raw,
        clone_url_normalised=clone_url_normalised,
        detected_clone_url=detected_clone_url,
        clone_url_verification=clone_url_verification,
        # GIT only with a clone URL (ck_repositories_clone_url_required_for_git), as repository-ingest records it.
        source_control_status="GIT" if has_git and clone_url_raw else "NONE",
        source_type="local_path",
        provider=derive_provider(clone_url_raw),
        default_branch=payload.default_branch,
        description=payload.description,
        technical_owner=payload.technical_owner,
        criticality=payload.criticality,
        retirement_status=payload.retirement_status,
        tags=payload.tags,
        notes=payload.notes,
        has_git_history=has_git,
        ingest_status="registered",
        ingest_token=str(uuid.uuid4()),
        first_registered_at=now,
    )
    db.add(repo)
    db.flush()
    return repo


# ---------- Registration by git URL (docs/VDI-SETUP.md: Registering a client repository) ----------


def name_from_url(clone_url: str) -> str:
    """The repository's name in its URL: the last path segment, without .git."""
    tail = re.split(r"[/:\\]", clone_url.strip().rstrip("/\\"))[-1]
    return tail[: -len(".git")] if tail.lower().endswith(".git") else tail or "repository"


def default_clone_folder(engagement_id: str, clone_url: str) -> Path | None:
    """<REPOS_DIR>\\<engagement>\\<repository>, or None when REPOS_DIR is not set."""
    base = settings.repos_path
    return None if base is None else base / engagement_id / name_from_url(clone_url)


def _target_folder_problems(folder: Path) -> list[str]:
    if not folder.is_absolute():
        return [f"'{folder}' is not an absolute path."]
    text = str(folder).rstrip("\\/").lower()
    if _DRIVE_ROOT_RE.match(str(folder)) or text in _SYSTEM_LOCATIONS:
        return [f"'{folder}' is a system location: choose a folder of your own."]
    resolved = folder.resolve()
    if resolved.is_relative_to(Path(settings.platform_root).resolve()):
        return [f"'{folder}' is inside the platform's own folder: clone client repositories outside it."]
    if resolved.is_relative_to(settings.runs_path.resolve()):
        return [f"'{folder}' is inside RUNS_DIR, the platform's run output: clone client repositories outside it."]
    return []


def _resolve_target(engagement_id: str, clone_url: str, target_folder: str | None) -> tuple[Path | None, list[str]]:
    if target_folder and target_folder.strip():
        folder = Path(target_folder.strip())
        return folder, _target_folder_problems(folder)
    try:
        folder = default_clone_folder(engagement_id, clone_url)
    except ValueError as exc:
        return None, [str(exc)]
    if folder is None:
        return None, ["REPOS_DIR is not set, so there is no default folder: give the target folder to clone into."]
    return folder, _target_folder_problems(folder)


def inspect_url(db: Session, engagement_id: str, clone_url: str, target_folder: str | None) -> InspectUrlResponse:
    """Read-only: what registering this URL would do. Drives the registration form."""
    url = clone_url.strip()
    problems = [p["message"] for p in validate_clone_url(url, allow_file=True)] if url else ["Enter the git URL."]
    try:
        repos_dir = settings.repos_path
    except ValueError as exc:
        repos_dir, problems = None, problems + [str(exc)]
    folder, folder_problems = _resolve_target(engagement_id, url, target_folder) if url else (None, [])
    problems += folder_problems
    action, message, duplicate = None, None, None
    if folder is not None and not folder_problems and not problems:
        action, why = git_source.target_state(folder, url)
        message = {"clone": f"It will be cloned into {folder}.",
                   "reuse": f"{folder} is already a clone of this URL: it will be used as it is."}.get(action, why)
        if action == "refuse":
            problems.append(why)
        match = find_duplicate_conflict(db, engagement_id, repository_ingest.normalize_clone_url(url), folder.name,
                                        normalize_local_path(str(folder)))
        if match is not None:
            matched_on, existing = match
            duplicate = DuplicateConflict(matched_on=matched_on, repository_id=str(existing.id), slug=existing.slug,
                                          message=duplicate_conflict_message(db, engagement_id, existing, matched_on))
        if action == "reuse":
            elsewhere = find_checkout_in_other_engagement(db, engagement_id, str(folder))
            if elsewhere is not None:
                problems.append(checkout_in_other_engagement_message(elsewhere))
    return InspectUrlResponse(problems=problems, suggested_name=name_from_url(url) if url else None,
                              repos_dir=str(repos_dir) if repos_dir else None,
                              target_folder=str(folder) if folder else None, target_action=action,
                              target_message=message, duplicate_conflict=duplicate)


def register_git_clone(db: Session, engagement: models.Engagement, payload: RegisterGitCloneRequest) -> models.Repository:
    """Registers a repository by its git URL. Nothing is cloned here: the repository's ingest job clones it (or uses
    an existing clone of the same URL), so the clone's progress and errors show in the job."""
    url = payload.clone_url.strip()
    problems = validate_clone_url(url, allow_file=True)
    if problems:
        raise RegistrationError(422, problems)
    folder, folder_problems = _resolve_target(engagement.id, url, payload.target_folder)
    if folder_problems:
        raise RegistrationError(422, [{"field": "target_folder", "message": m, "code": "INVALID_TARGET_FOLDER"}
                                      for m in folder_problems])
    action, why = git_source.target_state(folder, url)
    if action == "refuse":
        raise RegistrationError(409, [{"field": "target_folder", "message": why, "code": "TARGET_FOLDER_NOT_EMPTY"}])

    clone_url_normalised = repository_ingest.normalize_clone_url(url)
    local_path_normalised = normalize_local_path(str(folder))
    conflict = find_duplicate_conflict(db, engagement.id, clone_url_normalised, folder.name, local_path_normalised)
    if conflict is not None:
        matched_on, existing = conflict
        raise RegistrationError(409, [{"field": None, "code": f"DUPLICATE_{matched_on.upper()}",
                                       "message": duplicate_conflict_message(db, engagement.id, existing, matched_on)}])
    elsewhere = find_checkout_in_other_engagement(db, engagement.id, str(folder))
    if elsewhere is not None:
        raise RegistrationError(409, [{"field": "target_folder", "code": "CHECKOUT_IN_OTHER_ENGAGEMENT",
                                       "message": checkout_in_other_engagement_message(elsewhere)}])
    nesting = find_nesting_conflict(db, engagement.id, local_path_normalised)
    if nesting is not None:
        raise RegistrationError(409, [{"field": "target_folder", "code": "NESTED_PATH",
                                       "message": f"'{folder}' is a parent or descendant of already-registered "
                                                  f'repository "{nesting.slug}" ({nesting.local_path}).'}])

    now = datetime.datetime.now(datetime.timezone.utc)
    repo = models.Repository(
        id=uuid.uuid4(),
        engagement_id=engagement.id,
        name=payload.name or name_from_url(url),
        root_folder_name=folder.name,
        slug=_unique_slug(db, engagement.id, slugify(folder.name)),
        local_path=str(folder),
        local_path_normalised=local_path_normalised,
        clone_url=url,
        clone_url_normalised=clone_url_normalised,
        detected_clone_url=None,
        # Verified by repository-ingest once the clone exists: its origin is this URL.
        clone_url_verification="unverifiable",
        source_control_status="NONE",
        source_type="git_clone",
        provider=derive_provider(url) if not url.startswith("file:") else "other",
        default_branch=(payload.branch or "").strip() or None,
        description=payload.description,
        technical_owner=payload.technical_owner,
        criticality=payload.criticality,
        retirement_status=payload.retirement_status,
        tags=payload.tags,
        notes=payload.notes,
        has_git_history=False,
        ingest_status="registered",
        ingest_token=str(uuid.uuid4()),
        first_registered_at=now,
    )
    db.add(repo)
    db.flush()
    return repo


# ---------- Existing data a later rule would refuse (CLAUDE.md rule 15) ----------


def shared_checkouts(db: Session) -> list[list[models.Repository]]:
    """Checkouts registered in more than one engagement: refused since rbc-release-2, but an installation upgraded
    from rbc-release-1 may already have them. Reported, never changed: each registration keeps working as it did."""
    groups: dict[str, list[models.Repository]] = {}
    for repo in db.query(models.Repository).filter(models.Repository.deleted_at.is_(None)).order_by(
            models.Repository.engagement_id, models.Repository.slug):
        path = Path(repo.local_path)
        key = repo.local_path_normalised.lower()
        if (path / ".git").exists():
            key = (git_common_dir(path) or key).lower()
        groups.setdefault(key, []).append(repo)
    return [g for g in groups.values() if len({r.engagement_id for r in g}) > 1]


def shared_checkout_message(group: list[models.Repository]) -> str:
    named = ", ".join(f"{r.engagement_id}/{r.slug}" for r in group)
    return (f"One checkout is registered in {len({r.engagement_id for r in group})} engagements ({named}, "
            f"{group[0].local_path}). Registered before rbc-release-2 refused it, so it is left working. Their "
            "conversion branches share names in that checkout's git, so run conversions in one engagement only, or "
            "clone the repository again for the other engagement, register the new clone there, and delete the old "
            "registration (docs/VDI-SETUP.md: More than one person).")


# ---------- Lifecycle operations ----------


def list_repositories(
    db: Session,
    engagement_id: str,
    include_deleted: bool = False,
    ingest_status: str | None = None,
    criticality: str | None = None,
    retirement_status: str | None = None,
    q: str | None = None,
) -> list[models.Repository]:
    query = db.query(models.Repository).filter(models.Repository.engagement_id == engagement_id)
    if not include_deleted:
        query = query.filter(models.Repository.deleted_at.is_(None))
    if ingest_status:
        query = query.filter(models.Repository.ingest_status == ingest_status)
    if criticality:
        query = query.filter(models.Repository.criticality == criticality)
    if retirement_status:
        query = query.filter(models.Repository.retirement_status == retirement_status)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                models.Repository.name.ilike(like),
                models.Repository.root_folder_name.ilike(like),
                models.Repository.technical_owner.ilike(like),
            )
        )
    return query.order_by(models.Repository.name).all()


def update_repository(repo: models.Repository, payload: RepositoryUpdate) -> None:
    """Only the editable metadata fields — never local_path, clone_url or
    root_folder_name, which are identity."""
    repo.name = payload.name
    repo.description = payload.description
    repo.technical_owner = payload.technical_owner
    repo.criticality = payload.criticality
    repo.retirement_status = payload.retirement_status
    repo.tags = payload.tags
    repo.notes = payload.notes
    repo.default_branch = payload.default_branch
    repo.updated_at = datetime.datetime.now(datetime.timezone.utc)


def soft_delete(repo: models.Repository, deleted_by: str | None) -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    repo.deleted_at = now
    repo.deleted_by = deleted_by


def restore(repo: models.Repository) -> None:
    repo.deleted_at = None
    repo.deleted_by = None


def start_rescan(repo: models.Repository) -> str:
    """Generates a new ingest_token — a rescan is a distinct job instance,
    not a restart of the previous one (15-REPOSITORY-INGEST-UI.md Part A).
    Caller launches phase0-repository-discovery with the new token."""
    repo.ingest_token = str(uuid.uuid4())
    return repo.ingest_token


def verify_path(repo: models.Repository) -> bool:
    """Re-checks local_path still exists. Returns the current existence."""
    exists = Path(repo.local_path).is_dir()
    if not exists:
        repo.ingest_status = "path_missing"
    elif repo.ingest_status == "path_missing":
        repo.ingest_status = "registered"
    return exists
