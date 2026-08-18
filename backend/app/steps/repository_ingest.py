"""Lifecycle step 1 — repository estate ingest & inventory creation. See
13-STEP-001-REPOSITORY-INGEST.md and 15-REPOSITORY-INGEST-UI.md Parts B and C.

`local_path` is the only implemented source: the repository already exists on
disk, at the path recorded on its `repositories` row (never from step
`config` — that row is authoritative, set once at registration). A row whose
`source_type` is anything else is out of scope for this implementation and
returns `NOT_IMPLEMENTED` rather than guessing.

Phase 0 is read-only against the registered folder: this module only ever
opens files under `local_path` for reading, and writes exclusively under
`output_dir`.
"""

import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.workflow.adapters.base import compute_checksum
from app.workflow.contract import StepContext, StepOutput, StepResult

ARTIFACT_TYPE = "repository-inventory"
ARTIFACT_VERSION = "1.1.0"

SKIP_DIR_NAMES = {".git", "node_modules", "bin", "obj", "packages"}

# docs/19-STEP-002-SOLUTION-DISCOVERY.md Part A — "Language detection".
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
    credentials, and treat git@host:org/repo as https://host/org/repo."""
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
    return f"{parsed.scheme}://{host}{path}"


def derive_organization(clone_url: str) -> str | None:
    """First path segment of the clone URL — `github.com/acme/orders` ->
    `acme`. Null when the URL has no path segment to parse (docs/19 Part A)."""
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
    engine = create_engine(database_url)
    return sessionmaker(bind=engine)(), engine


def _iso_utc(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


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

        if repo.source_type != "local_path":
            return StepResult(
                exit_status="NOT_IMPLEMENTED",
                exit_message=(
                    f"source_type '{repo.source_type}' is not implemented; only "
                    "'local_path' is supported"
                ),
            )

        local_path = Path(repo.local_path)
        now = datetime.datetime.now(datetime.timezone.utc)

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

        if detected_clone_url is None:
            clone_url_verification = "unverifiable"
        elif normalize_clone_url(detected_clone_url) == normalize_clone_url(repo.clone_url):
            clone_url_verification = "verified"
        else:
            clone_url_verification = "mismatch"

        last_commit_date = (
            datetime.datetime.fromisoformat(last_commit_date_raw) if last_commit_date_raw else None
        )
        organization = derive_organization(repo.clone_url)
        # source_status is only knowable via a provider API — local_path is
        # the only implemented source_type, so it always stays null here.
        source_status = None

        size_bytes, file_count, language_counts = compute_size_metrics(local_path)
        primary_languages = summarize_primary_languages(language_counts)

        repo.has_git_history = has_git_history
        repo.ingest_commit_sha = ingest_commit_sha
        repo.detected_clone_url = detected_clone_url
        repo.clone_url_verification = clone_url_verification
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
        # 13-STEP-001-REPOSITORY-INGEST.md. It would make the checksum differ
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
            "clone_url": repo.clone_url,
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
            exit_message=f"Ingested repository '{repo.slug}' (clone URL {clone_url_verification})",
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
