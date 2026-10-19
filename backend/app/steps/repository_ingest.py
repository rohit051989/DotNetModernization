"""Lifecycle step 1 — repository estate ingest & inventory creation. See
13-REPOSITORY-INGEST.md and 15-REPOSITORY-INGEST-UI.md Parts B and C.

Two sources: `local_path`, a repository already on disk at the path recorded on its `repositories` row (never from
step `config` — that row is authoritative, set once at registration); and `git_clone`, a repository registered by its
git URL, which this step first clones into that path, or, on a rescan, fetches and fast-forwards
(docs/VDI-SETUP.md: Registering a client repository). Apart from that clone or update, this step is read-only against the registered
folder: it only ever opens files under `local_path` for reading, and writes exclusively under `output_dir`.
"""

import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


from sqlalchemy.orm import sessionmaker

from app import models
from app.db import make_engine
from app.workflow.adapters.base import compute_checksum
from app.workflow.contract import StepContext, StepOutput, StepResult

ARTIFACT_TYPE = "repository-inventory"
# 1.2.0: added source_control_status, and clone_url may now be null
# (15-REPOSITORY-INGEST-UI.md Part C) — additive, solution-discovery's
# consumes range (^1.0.0) still accepts it.
ARTIFACT_VERSION = "1.2.0"

SKIP_DIR_NAMES = {".git", "node_modules", "bin", "obj", "packages"}

# docs/19-SOLUTION-DISCOVERY.md Part A — "Language detection".
EXTENSION_LANGUAGE_MAP = {
    ".cs": "C#",
    ".vb": "VB.NET",
    ".fs": "F#",
    ".sql": "SQL",
    ".ps1": "PowerShell",
    ".js": "JavaScript/TypeScript",
    ".ts": "JavaScript/TypeScript",
    ".xml": "XML",
    ".config": "XML",
    ".xaml": "XML",
    ".cshtml": "Razor/WebForms markup",
    ".aspx": "Razor/WebForms markup",
    ".ascx": "Razor/WebForms markup",
    ".html": "Web",
    ".css": "Web",
}

PRIMARY_LANGUAGES_LIMIT = 6

_SSH_URL_RE = re.compile(r"^git@([^:]+):(.+?)(?:\.git)?/?$")


def normalize_clone_url(url: str) -> str:
    """Clone URL normalisation per 15-REPOSITORY-INGEST-UI.md Part C:
    lowercase host, strip trailing .git, strip trailing slash, strip embedded
    credentials, and treat an SSH remote — git@host:org/repo or
    ssh://[user@]host[:port]/org/repo — as https://host/org/repo, so the same
    repository has one identity however it was cloned."""
    url = url.strip()
    ssh_match = _SSH_URL_RE.match(url)
    if ssh_match:
        host, path = ssh_match.group(1), ssh_match.group(2)
        return f"https://{host.lower()}/{path.strip('/')}"

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    path = path.rstrip("/")
    scheme = "https" if parsed.scheme == "ssh" else parsed.scheme
    return f"{scheme}://{host}{path}"


def derive_organization(clone_url: str | None) -> str | None:
    """First path segment of the clone URL — `github.com/acme/orders` ->
    `acme`. Null when the URL has no path segment to parse (docs/19 Part A),
    or there is no clone URL at all (a folder never under source control)."""
    if not clone_url:
        return None
    path = urlparse(normalize_clone_url(clone_url)).path.strip("/")
    if not path:
        return None
    return path.split("/")[0]


def run_git(local_path: Path, *args: str) -> str | None:
    """Runs `git <args>` in `local_path`. Returns None on any failure — a
    missing git executable, a non-zero exit, or empty output — rather than
    raising; the caller treats that as "could not resolve"."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(local_path), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    output = completed.stdout.strip()
    return output or None


def compute_size_metrics(local_path: Path) -> tuple[int, int, dict[str, int]]:
    """Total size, file count and per-language file counts under
    `local_path`, skipping SKIP_DIR_NAMES entirely (pruned from traversal,
    not just excluded from the count). Language counts feed
    `summarize_primary_languages` — see docs/19 Part A."""
    total_size = 0
    total_files = 0
    language_counts: dict[str, int] = {}
    for root, dirs, files in os.walk(local_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIR_NAMES]
        for filename in files:
            file_path = Path(root) / filename
            try:
                total_size += file_path.stat().st_size
            except OSError:
                continue
            total_files += 1
            language = EXTENSION_LANGUAGE_MAP.get(file_path.suffix.lower())
            if language:
                language_counts[language] = language_counts.get(language, 0) + 1
    return total_size, total_files, language_counts


def summarize_primary_languages(language_counts: dict[str, int]) -> list[dict]:
    """`{language, file_count, percentage}`, descending by count, top 6.
    Percentages are of counted files only (docs/19 Part A) — files with an
    unrecognised extension don't contribute to the denominator."""
    counted_total = sum(language_counts.values())
    ranked = sorted(language_counts.items(), key=lambda item: item[1], reverse=True)
    return [
        {
            "language": language,
            "file_count": count,
            "percentage": round(count / counted_total * 100, 1) if counted_total else 0.0,
        }
        for language, count in ranked[:PRIMARY_LANGUAGES_LIMIT]
    ]


def _open_session(database_url: str):
    """A fresh engine per invocation, not a shared pool — this step is meant
    to run standalone (see the __main__ entry) as well as in-process, so it
    does not assume `app.db`'s global engine is available or appropriate.
    Disposed by the caller alongside closing the session."""
    engine = make_engine(database_url)
    return sessionmaker(bind=engine)(), engine


def _iso_utc(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _bring_clone_up_to_date(db, repo) -> tuple[str | None, str | None]:
    """For a repository registered by its git URL (app/repositories/git_source.py): clones it when its folder does
    not exist or is empty; on its first ingest uses an existing clone of the same URL as it is; on every later one
    fetches and fast-forwards its branch, refusing when the clone has local changes. Returns (what happened, None) or
    (None, why it failed). git's progress goes to repositories.clone_progress while it runs."""
    from app.repositories import git_source

    folder = Path(repo.local_path)
    action, why = git_source.target_state(folder, repo.clone_url)
    try:
        if action == "refuse":
            return None, why
        if action == "clone":
            repo.ingest_status, repo.clone_progress = "cloning", f"Cloning {repo.clone_url}"
            db.commit()

            def progress(line: str) -> None:
                repo.clone_progress = line[:300]
                db.commit()

            git_source.clone(repo.clone_url, repo.default_branch, folder, progress)
            branch = run_git(folder, "rev-parse", "--abbrev-ref", "HEAD")
            repo.default_branch = repo.default_branch or branch
            note = f"cloned {repo.clone_url} ({branch}) into {folder}"
        elif repo.last_scanned_at is None:
            branch = run_git(folder, "rev-parse", "--abbrev-ref", "HEAD")
            if repo.default_branch and branch != repo.default_branch:
                return None, (f"The existing clone at '{folder}' is on {branch}, not {repo.default_branch}. Switch it "
                              f"(git -C \"{folder}\" switch {repo.default_branch}) and Rescan, or register again "
                              "without a branch.")
            repo.default_branch = repo.default_branch or branch
            note = f"used the existing clone of {repo.clone_url} at {folder} as it is"
        else:
            repo.ingest_status, repo.clone_progress = "cloning", f"Fetching {repo.clone_url}"
            db.commit()
            branch = repo.default_branch or run_git(folder, "rev-parse", "--abbrev-ref", "HEAD")
            note = git_source.update(folder, repo.clone_url, branch)
            repo.default_branch = branch
    except git_source.GitSourceError as exc:
        return None, str(exc)
    except OSError as exc:
        return None, f"git could not run: {exc}"
    repo.clone_progress = None
    db.commit()
    return note, None


def run(context: StepContext) -> StepResult:
    repository_id = context.parameters.get("repository_id")
    if not repository_id:
        return StepResult(
            exit_status="FAILED",
            exit_message="parameters.repository_id is required for repository-ingest",
        )
    if not context.database_url:
        return StepResult(exit_status="FAILED", exit_message="database_url is required")

    db, engine = _open_session(context.database_url)
    try:
        repo = db.get(models.Repository, repository_id)
        if repo is None:
            return StepResult(
                exit_status="FAILED", exit_message=f"repository '{repository_id}' does not exist"
            )

        if repo.source_type not in ("local_path", "git_clone"):
            return StepResult(
                exit_status="NOT_IMPLEMENTED",
                exit_message=f"source_type '{repo.source_type}' is not implemented",
            )

        local_path = Path(repo.local_path)
        now = datetime.datetime.now(datetime.timezone.utc)

        source_note = None
        if repo.source_type == "git_clone":
            source_note, failure = _bring_clone_up_to_date(db, repo)
            if failure:
                repo.ingest_status = "scan_failed"
                repo.ingest_error = failure
                repo.clone_progress = None
                repo.last_scanned_at = now
                db.commit()
                return StepResult(exit_status="FAILED", exit_message=failure)

        if not local_path.is_dir():
            repo.ingest_status = "path_missing"
            repo.ingest_error = f"local_path '{repo.local_path}' does not exist or is not a directory"
            repo.last_scanned_at = now
            db.commit()
            return StepResult(exit_status="FAILED", exit_message=repo.ingest_error)

        has_git_history = (local_path / ".git").is_dir()
        ingest_commit_sha = None
        current_branch = None
        detected_clone_url = None
        last_commit_date_raw = None
        if has_git_history:
            ingest_commit_sha = run_git(local_path, "rev-parse", "HEAD")
            current_branch = run_git(local_path, "rev-parse", "--abbrev-ref", "HEAD")
            detected_clone_url = run_git(local_path, "config", "--get", "remote.origin.url")
            last_commit_date_raw = run_git(local_path, "log", "-1", "--format=%cI")

        clone_url = repo.clone_url
        if has_git_history and not clone_url and detected_clone_url:
            # The "migrating into source control" case, but discovered on
            # rescan rather than at registration: the folder had no clone
            # URL when it was registered (source_control_status NONE), and
            # now has a git remote. Backfill from the detected remote rather
            # than leaving clone_url null with source_control_status GIT,
            # which ck_repositories_clone_url_required_for_git forbids.
            clone_url = detected_clone_url
            repo.clone_url = clone_url
            repo.clone_url_normalised = normalize_clone_url(clone_url)

        # GIT only once there is a clone_url to go with it — see the
        # constraint above. A .git directory with no remote and no
        # operator-supplied URL is real (has_git_history still says so) but
        # isn't yet a fully-identified repository from this platform's
        # registration model, so source_control_status stays NONE for it.
        source_control_status = "GIT" if has_git_history and clone_url else "NONE"

        if not has_git_history:
            clone_url_verification = "unverifiable" if clone_url else "not_applicable"
        elif detected_clone_url is None:
            clone_url_verification = "unverifiable" if clone_url else "not_applicable"
        elif clone_url and normalize_clone_url(detected_clone_url) == normalize_clone_url(clone_url):
            clone_url_verification = "verified"
        else:
            clone_url_verification = "mismatch"

        last_commit_date = (
            datetime.datetime.fromisoformat(last_commit_date_raw) if last_commit_date_raw else None
        )
        organization = derive_organization(clone_url)
        # source_status is only knowable via a provider API — local_path is
        # the only implemented source_type, so it always stays null here.
        source_status = None

        size_bytes, file_count, language_counts = compute_size_metrics(local_path)
        primary_languages = summarize_primary_languages(language_counts)

        repo.has_git_history = has_git_history
        repo.ingest_commit_sha = ingest_commit_sha
        repo.detected_clone_url = detected_clone_url
        repo.clone_url_verification = clone_url_verification
        repo.source_control_status = source_control_status
        repo.size_bytes = size_bytes
        repo.file_count = file_count
        repo.organization = organization
        repo.last_commit_date = last_commit_date
        repo.primary_languages = primary_languages
        repo.source_status = source_status
        repo.ingest_status = "scanned"
        repo.ingest_error = None
        repo.last_scanned_at = now
        db.commit()

        # generated_at is deliberately NOT part of this file — see
        # 13-REPOSITORY-INGEST.md. It would make the checksum differ
        # between two runs over an unchanged repository, since the engine's
        # checksum is computed over the file's actual bytes. It's carried in
        # the output's `metadata` instead.
        inventory = {
            "artifact_type": ARTIFACT_TYPE,
            "artifact_version": ARTIFACT_VERSION,
            "engagement_id": repo.engagement_id,
            "repository_id": str(repo.id),
            "slug": repo.slug,
            "name": repo.name,
            "root_folder_name": repo.root_folder_name,
            "local_path": repo.local_path,
            "source_type": repo.source_type,
            "clone_url": clone_url,
            "source_control_status": source_control_status,
            "detected_clone_url": detected_clone_url,
            "clone_url_verification": clone_url_verification,
            "provider": repo.provider,
            "default_branch": repo.default_branch,
            "current_branch": current_branch,
            "has_git_history": has_git_history,
            "ingest_commit_sha": ingest_commit_sha,
            "size_bytes": size_bytes,
            "file_count": file_count,
            "organization": organization,
            "last_commit_date": _iso_utc(last_commit_date) if last_commit_date else None,
            "primary_languages": primary_languages,
            "source_status": source_status,
        }

        output_dir = Path(context.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "repository-inventory.json"
        output_path.write_text(
            json.dumps(inventory, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        checksum = compute_checksum(output_path.as_uri())

        return StepResult(
            exit_status="COMPLETED",
            exit_message=f"Ingested repository '{repo.slug}' (clone URL {clone_url_verification})"
            + (f"; {source_note}" if source_note else ""),
            metrics={"read_count": 1, "write_count": 1, "skip_count": 0, "commit_count": 1},
            outputs=[
                StepOutput(
                    artifact_type=ARTIFACT_TYPE,
                    artifact_version=ARTIFACT_VERSION,
                    uri=output_path.as_uri(),
                    checksum=checksum,
                    metadata={"generated_at": _iso_utc(now)},
                )
            ],
        )
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    _raw_context = json.load(sys.stdin)
    _context = StepContext.model_validate(_raw_context)
    try:
        _result = run(_context)
    except Exception as exc:  # a "process"-style invocation must still emit valid JSON
        _result = StepResult(exit_status="FAILED", exit_message=f"{type(exc).__name__}: {exc}")
    sys.stdout.write(_result.model_dump_json())
