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
ARTIFACT_VERSION = "1.0.0"

SKIP_DIR_NAMES = {".git", "node_modules", "bin", "obj", "packages"}

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


def _run_git(local_path: Path, *args: str) -> str | None:
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


def compute_size_metrics(local_path: Path) -> tuple[int, int]:
    """Total size and file count under `local_path`, skipping SKIP_DIR_NAMES
    entirely (pruned from traversal, not just excluded from the count)."""
    total_size = 0
    total_files = 0
    for root, dirs, files in os.walk(local_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIR_NAMES]
        for filename in files:
            file_path = Path(root) / filename
            try:
                total_size += file_path.stat().st_size
            except OSError:
                continue
            total_files += 1
    return total_size, total_files


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
        if has_git_history:
            ingest_commit_sha = _run_git(local_path, "rev-parse", "HEAD")
            current_branch = _run_git(local_path, "rev-parse", "--abbrev-ref", "HEAD")
            detected_clone_url = _run_git(local_path, "config", "--get", "remote.origin.url")

        if detected_clone_url is None:
            clone_url_verification = "unverifiable"
        elif normalize_clone_url(detected_clone_url) == normalize_clone_url(repo.clone_url):
            clone_url_verification = "verified"
        else:
            clone_url_verification = "mismatch"

        size_bytes, file_count = compute_size_metrics(local_path)

        repo.has_git_history = has_git_history
        repo.ingest_commit_sha = ingest_commit_sha
        repo.detected_clone_url = detected_clone_url
        repo.clone_url_verification = clone_url_verification
        repo.size_bytes = size_bytes
        repo.file_count = file_count
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
