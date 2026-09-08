import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error, errors
from app.repositories import service as repositories_service
from app.repositories.schemas import (
    InspectPathRequest,
    InspectPathResponse,
    RegisterGitCloneRequest,
    RegisterLocalPathRequest,
    RegisterRepositoryRequest,
    RegisterRepositoryResponse,
    RepositoryDetail,
    RepositorySoftDeleteResponse,
    RepositorySummary,
    RepositoryUpdate,
    RescanResponse,
    VerifyPathResponse,
)
from app.repositories.service import RegistrationError
from app.workflow.runtime import service as runtime_service
from app.workflow.runtime.schemas import JobExecutionOut

router = APIRouter(prefix="/api", tags=["Repositories"])

_DISCOVERY_JOB = "phase0-repository-discovery"

_REPOSITORY_NOT_FOUND = {
    "model": ErrorResponse,
    "description": "No repository exists with this id (or it is soft-deleted and `include_deleted` was not set).",
}


def _get_engagement(db: Session, engagement_id: str) -> models.Engagement:
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None or engagement.deleted_at is not None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    return engagement


def _get_repository(db: Session, repository_id: uuid.UUID, include_deleted: bool = False) -> models.Repository:
    repo = db.get(models.Repository, repository_id)
    if repo is None or (repo.deleted_at is not None and not include_deleted):
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")
    return repo


def _launch_discovery(
    db: Session, background_tasks: BackgroundTasks, engagement_id: str, repository_id: uuid.UUID, ingest_token: str
) -> models.WfJobExecution:
    """Synchronous creation, asynchronous execution — 15-REPOSITORY-INGEST-UI.md
    Part E: the job instance and this first execution are created (and, along
    with the repositories row, committed) before returning, so the response
    carries a trackable job_execution_id. The actual run happens after the
    response is sent, via BackgroundTasks."""
    try:
        job_execution, instance, definition = runtime_service.create_execution(
            db,
            _DISCOVERY_JOB,
            {
                "engagement_id": engagement_id,
                "repository_id": str(repository_id),
                "ingest_token": ingest_token,
            },
            triggered_by="api",
        )
    except LookupError as exc:
        raise error(500, str(exc), code="JOB_DEFINITION_NOT_ACTIVE") from exc
    except (runtime_service.PreconditionError,) as exc:
        raise errors(422, exc.failures) from exc

    db.commit()
    db.refresh(job_execution)

    background_tasks.add_task(
        runtime_service.run_execution_in_background,
        job_execution.id,
        instance.id,
        definition.model_dump(mode="json"),
    )
    return job_execution


def _repository_out(db: Session, repo: models.Repository, detail: bool = False):
    if not detail:
        return RepositorySummary.model_validate(repo)

    latest = runtime_service.list_executions(
        db, job_name=_DISCOVERY_JOB, repository_id=str(repo.id), limit=1
    )
    latest_execution = runtime_service.to_execution_out(db, latest[0]) if latest else None
    return RepositoryDetail(
        **RepositorySummary.model_validate(repo).model_dump(),
        local_path=repo.local_path,
        clone_url=repo.clone_url,
        source_control_status=repo.source_control_status,
        detected_clone_url=repo.detected_clone_url,
        default_branch=repo.default_branch,
        description=repo.description,
        technical_owner=repo.technical_owner,
        tags=repo.tags,
        notes=repo.notes,
        ingest_commit_sha=repo.ingest_commit_sha,
        ingest_error=repo.ingest_error,
        ingest_token=repo.ingest_token,
        first_registered_at=repo.first_registered_at,
        created_at=repo.created_at,
        updated_at=repo.updated_at,
        deleted_by=repo.deleted_by,
        organization=repo.organization,
        last_commit_date=repo.last_commit_date,
        primary_languages=repo.primary_languages,
        source_status=repo.source_status,
        latest_execution=latest_execution,
    )


@router.post(
    "/engagements/{engagement_id}/repositories/inspect-path",
    response_model=InspectPathResponse,
    summary="Inspect a local folder path before registering it",
    response_description="Detected git metadata, shallow solution/project counts, sampled size estimates, and any duplicate conflict or warnings.",
    operation_id="inspect_repository_path",
    responses={404: {"model": ErrorResponse, "description": "No engagement exists with this id."}},
)
def inspect_path(engagement_id: str, payload: InspectPathRequest, db: Session = Depends(get_db)):
    """
    Read-only — does not register anything. Drives the registration form:
    called on blur as the operator pastes a path. `estimated_file_count` and
    `estimated_size_bytes` are sampled and capped, not exhaustive; label them
    as estimates in the UI. `duplicate_conflict` is populated from the
    detected git remote and the path alone, before the operator has typed a
    clone URL or anything else.
    """
    _get_engagement(db, engagement_id)
    return repositories_service.inspect_path(db, engagement_id, payload.local_path)


@router.post(
    "/engagements/{engagement_id}/repositories/register",
    response_model=RegisterRepositoryResponse,
    status_code=202,
    summary="Register a repository and launch discovery",
    response_description="Accepted. Discovery has been launched; track it via job_execution_id.",
    operation_id="register_repository",
    responses={
        404: {"model": ErrorResponse, "description": "No engagement exists with this id."},
        409: {
            "model": ErrorResponse,
            "description": "Duplicate clone URL, root folder name, or local path; or the path nests inside an already-registered path.",
        },
        422: {
            "model": ErrorResponse,
            "description": "The path is relative, doesn't exist, is a system location, or is empty; or the clone URL is malformed or embeds credentials.",
        },
        501: {"model": ErrorResponse, "description": "source_type git_clone is not yet implemented."},
    },
)
def register_repository(
    engagement_id: str,
    payload: RegisterRepositoryRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Registers an existing repository folder and immediately launches
    `phase0-repository-discovery` for it.

    The folder is read **in place** and never copied or modified. The clone
    URL you supply is verified against the folder's git remote where
    present; a mismatch is reported but does not block registration.

    Returns 202 rather than 201 because discovery runs asynchronously — the
    repository row and the first job execution are created and committed
    before this responds, but the execution itself runs after the response
    is sent. Poll `GET /api/repositories/{id}` or
    `GET /api/workflow/executions/{job_execution_id}` to follow progress.
    """
    engagement = _get_engagement(db, engagement_id)

    if isinstance(payload, RegisterGitCloneRequest):
        raise error(
            501,
            "Clone-from-URL registration is not yet available. Clone the repository "
            "manually and register its local path. Supported source types: local_path.",
            code="NOT_IMPLEMENTED",
        )

    assert isinstance(payload, RegisterLocalPathRequest)
    try:
        repo = repositories_service.register_local_path(db, engagement, payload)
    except RegistrationError as exc:
        raise errors(exc.status_code, exc.errors) from exc

    job_execution = _launch_discovery(db, background_tasks, engagement_id, repo.id, repo.ingest_token)
    db.refresh(repo)

    return RegisterRepositoryResponse(
        repository_id=str(repo.id),
        slug=repo.slug,
        ingest_token=repo.ingest_token,
        job_execution_id=str(job_execution.id),
        clone_url_verification=repo.clone_url_verification,
        status="processing",
    )


@router.get(
    "/engagements/{engagement_id}/repositories",
    response_model=list[RepositorySummary],
    summary="List repositories for an engagement",
    response_description="Repositories matching the filters, ordered by name.",
    operation_id="list_repositories",
    responses={404: {"model": ErrorResponse, "description": "No engagement exists with this id."}},
)
def list_repositories(
    engagement_id: str,
    include_deleted: bool = Query(False, description="Include soft-deleted repositories."),
    ingest_status: str | None = Query(None, description="Filter by 'registered', 'scanned', 'scan_failed', or 'path_missing'."),
    criticality: str | None = Query(None, description="Filter by 'low', 'medium', 'high', or 'critical'."),
    retirement_status: str | None = Query(None, description="Filter by 'active', 'slated_for_retirement', or 'decommissioned'."),
    q: str | None = Query(None, description="Case-insensitive substring match against name, root folder, and technical owner."),
    db: Session = Depends(get_db),
):
    _get_engagement(db, engagement_id)
    repos = repositories_service.list_repositories(
        db,
        engagement_id,
        include_deleted=include_deleted,
        ingest_status=ingest_status,
        criticality=criticality,
        retirement_status=retirement_status,
        q=q,
    )
    return [_repository_out(db, r) for r in repos]


@router.get(
    "/repositories/{repository_id}",
    response_model=RepositoryDetail,
    summary="Get a repository, including its latest discovery execution",
    response_description="The repository detail, with latest_execution populated if discovery has ever run.",
    operation_id="get_repository",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def get_repository(
    repository_id: uuid.UUID,
    include_deleted: bool = Query(False, description="Return the repository even if it is soft-deleted."),
    db: Session = Depends(get_db),
):
    repo = _get_repository(db, repository_id, include_deleted)
    return _repository_out(db, repo, detail=True)


@router.put(
    "/repositories/{repository_id}",
    response_model=RepositoryDetail,
    summary="Update a repository's editable metadata",
    response_description="The updated repository.",
    operation_id="update_repository",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def update_repository(repository_id: uuid.UUID, payload: RepositoryUpdate, db: Session = Depends(get_db)):
    """
    May change only `name`, `description`, `technical_owner`, `criticality`,
    `retirement_status`, `tags`, `notes` and `default_branch`. Cannot change
    `local_path`, `clone_url` or `root_folder_name` — those are identity.
    Relocating a repository means delete and re-register.
    """
    repo = _get_repository(db, repository_id)
    repositories_service.update_repository(repo, payload)
    db.commit()
    db.refresh(repo)
    return _repository_out(db, repo, detail=True)


@router.delete(
    "/repositories/{repository_id}",
    response_model=RepositorySoftDeleteResponse,
    summary="Soft-delete a repository",
    response_description="When the soft delete took effect.",
    operation_id="delete_repository",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def delete_repository(
    repository_id: uuid.UUID,
    deleted_by: str | None = Query(None, description="Free-text identity performing the delete — there is no auth system yet to source one from."),
    db: Session = Depends(get_db),
):
    repo = _get_repository(db, repository_id)
    repositories_service.soft_delete(repo, deleted_by)
    db.commit()
    return RepositorySoftDeleteResponse(id=repo.id, deleted_at=repo.deleted_at)


@router.post(
    "/repositories/{repository_id}/restore",
    response_model=RepositorySoftDeleteResponse,
    summary="Restore a soft-deleted repository",
    response_description="deleted_at is now null.",
    operation_id="restore_repository",
    responses={404: {"model": ErrorResponse, "description": "No repository exists with this id."}},
)
def restore_repository(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    """Admin-only in intent; unguarded for now — no auth system exists yet (see CLAUDE.md)."""
    # TODO: gate behind an admin role once auth exists.
    repo = _get_repository(db, repository_id, include_deleted=True)
    repositories_service.restore(repo)
    db.commit()
    return RepositorySoftDeleteResponse(id=repo.id, deleted_at=None)


@router.post(
    "/repositories/{repository_id}/rescan",
    response_model=RescanResponse,
    status_code=202,
    summary="Re-run discovery for a repository",
    response_description="Accepted. A new job instance (not a restart) has been launched.",
    operation_id="rescan_repository",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def rescan_repository(repository_id: uuid.UUID, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Generates a new `ingest_token`, which makes this a distinct job instance
    rather than a restart of the previous one — see
    15-REPOSITORY-INGEST-UI.md Part A. Runs asynchronously, same as
    registration.
    """
    repo = _get_repository(db, repository_id)
    ingest_token = repositories_service.start_rescan(repo)
    job_execution = _launch_discovery(db, background_tasks, repo.engagement_id, repo.id, ingest_token)
    db.refresh(repo)
    return RescanResponse(
        repository_id=repo.id, ingest_token=ingest_token, job_execution_id=job_execution.id, status="processing"
    )


@router.post(
    "/repositories/{repository_id}/verify-path",
    response_model=VerifyPathResponse,
    summary="Re-check that a repository's local path still exists",
    response_description="Whether the path currently exists; ingest_status is updated to path_missing if not.",
    operation_id="verify_repository_path",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def verify_repository_path(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    A lightweight existence check — not a rescan. So stale registrations are
    visible rather than failing mysteriously at the next scan.
    """
    repo = _get_repository(db, repository_id)
    exists = repositories_service.verify_path(repo)
    db.commit()
    return VerifyPathResponse(repository_id=repo.id, exists=exists, ingest_status=repo.ingest_status)


@router.get(
    "/repositories/{repository_id}/executions",
    response_model=list[JobExecutionOut],
    summary="List discovery executions for a repository",
    response_description="phase0-repository-discovery executions for this repository, newest first.",
    operation_id="list_repository_executions",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def list_repository_executions(
    repository_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500, description="Maximum executions to return."),
    offset: int = Query(0, ge=0, description="Number of executions to skip, for paging."),
    db: Session = Depends(get_db),
):
    repo = _get_repository(db, repository_id, include_deleted=True)
    executions = runtime_service.list_executions(
        db, repository_id=str(repo.id), limit=limit, offset=offset
    )
    return [runtime_service.to_execution_out(db, e) for e in executions]
