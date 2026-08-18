"""Read-only endpoints over step 2's (solution-discovery) results. See
19-STEP-002-SOLUTION-DISCOVERY.md Part I and 18-API-CONVENTIONS.md.

Nothing here mutates — solution-discovery (the standalone script under
steps/step-002-solution-discovery/) owns every row these routes read.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.structure import service as structure_service
from app.structure.schemas import (
    EngagementStructureSummaryOut,
    ProjectDetailOut,
    ProjectReferenceOut,
    ProjectSummaryOut,
    RepositoryArtifactOut,
    RepositoryStructureOut,
    SolutionOut,
)

router = APIRouter(prefix="/api", tags=["Solution Discovery"])

_REPOSITORY_NOT_FOUND = {"model": ErrorResponse, "description": "No repository exists with this id."}
_ENGAGEMENT_NOT_FOUND = {"model": ErrorResponse, "description": "No engagement exists with this id."}
_NOT_SCANNED = {
    "model": ErrorResponse,
    "description": "Solution discovery (lifecycle step 2) has not run yet for this repository.",
}


def _get_repository(db: Session, repository_id: uuid.UUID) -> models.Repository:
    repo = db.get(models.Repository, repository_id)
    if repo is None or repo.deleted_at is not None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")
    return repo


def _get_engagement(db: Session, engagement_id: str) -> models.Engagement:
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None or engagement.deleted_at is not None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    return engagement


@router.get(
    "/repositories/{repository_id}/structure",
    response_model=RepositoryStructureOut,
    summary="Get a repository's solution/project structure summary",
    response_description="Counts and rollups written by solution-discovery's last run.",
    operation_id="get_repository_structure",
    responses={404: _REPOSITORY_NOT_FOUND, 409: _NOT_SCANNED},
)
def get_repository_structure(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Rendered only when this exists; the UI shows an empty state naming step 2
    otherwise (Part I) — modelled here as 409 rather than a null-filled 200,
    since every field would otherwise have to be nullable for a state that is
    really "not scanned yet", not "scanned and empty".
    """
    _get_repository(db, repository_id)
    structure = structure_service.get_structure(db, repository_id)
    if structure is None:
        raise error(409, "Solution discovery has not run yet for this repository.", code="NOT_SCANNED")
    return RepositoryStructureOut.model_validate(structure)


@router.get(
    "/repositories/{repository_id}/solutions",
    response_model=list[SolutionOut],
    summary="List a repository's solutions with their member projects",
    response_description="Every `.sln` found, each with its declared project entries and their resolution status.",
    operation_id="list_repository_solutions",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def list_repository_solutions(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    _get_repository(db, repository_id)
    return structure_service.list_solutions(db, repository_id)


@router.get(
    "/repositories/{repository_id}/projects",
    response_model=list[ProjectSummaryOut],
    summary="List a repository's projects",
    response_description="Every project file found, raw metadata only — no interpretation beyond extension mapping.",
    operation_id="list_repository_projects",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def list_repository_projects(
    repository_id: uuid.UUID,
    framework_family: str | None = Query(None, description="Filter by normalised framework family, e.g. 'net-framework'."),
    project_format: str | None = Query(None, description="Filter by 'legacy_msbuild', 'sdk_style', or 'unknown'."),
    standalone: bool | None = Query(None, description="Filter to projects with (true) or without (false) solution membership."),
    q: str | None = Query(None, description="Case-insensitive substring match against name and relative path."),
    db: Session = Depends(get_db),
):
    _get_repository(db, repository_id)
    return structure_service.list_projects(
        db, repository_id, framework_family=framework_family, project_format=project_format, standalone=standalone, q=q
    )


@router.get(
    "/repositories/{repository_id}/project-references",
    response_model=list[ProjectReferenceOut],
    summary="List a repository's project-to-project references",
    response_description="Every <ProjectReference> declaration, with its resolution outcome.",
    operation_id="list_repository_project_references",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def list_repository_project_references(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    _get_repository(db, repository_id)
    return structure_service.list_project_references(db, repository_id)


@router.get(
    "/repositories/{repository_id}/artifacts",
    response_model=list[RepositoryArtifactOut],
    summary="List a repository's supporting artifacts",
    response_description="Build, pipeline, container, and other supporting files — presence only, no content interpretation.",
    operation_id="list_repository_artifacts",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def list_repository_artifacts(
    repository_id: uuid.UUID,
    category: str | None = Query(
        None, description="Filter by 'build', 'package', 'pipeline', 'container', 'script', 'configuration', 'deployment', or 'documentation'."
    ),
    db: Session = Depends(get_db),
):
    _get_repository(db, repository_id)
    return structure_service.list_repository_artifacts(db, repository_id, category=category)


@router.get(
    "/projects/{project_id}",
    response_model=ProjectDetailOut,
    summary="Get one project's detail",
    response_description="Full project metadata, including its packages and both directions of project references.",
    operation_id="get_project_detail",
    responses={404: {"model": ErrorResponse, "description": "No project exists with this id."}},
)
def get_project_detail(project_id: uuid.UUID, db: Session = Depends(get_db)):
    detail = structure_service.get_project_detail(db, project_id)
    if detail is None:
        raise error(404, f"Project '{project_id}' not found", code="NOT_FOUND")
    return detail


@router.get(
    "/engagements/{engagement_id}/structure-summary",
    response_model=EngagementStructureSummaryOut,
    summary="Get the engagement's portfolio-wide structure rollup",
    response_description="Solution/project counts summed across every scanned repository — feeds the dashboard's new cards.",
    operation_id="get_engagement_structure_summary",
    responses={404: _ENGAGEMENT_NOT_FOUND},
)
def get_engagement_structure_summary(engagement_id: str, db: Session = Depends(get_db)):
    _get_engagement(db, engagement_id)
    return structure_service.get_engagement_structure_summary(db, engagement_id)
