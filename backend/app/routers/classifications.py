"""Read-only endpoints over step 4's (pattern-classification) results. See
24-STEP-004-CLASSIFICATION.md Part I and 18-API-CONVENTIONS.md.

Nothing here mutates — the standalone script under
steps/step-004-classification/ owns every row these routes read.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models
from app.classification import service as classification_service
from app.classification.schemas import (
    CatalogCoverageOut,
    ClassificationListOut,
    ClassificationSummaryOut,
    PatternDistributionOut,
    ProjectClassificationDetailOut,
)
from app.db import get_db
from app.errors import ErrorResponse, error

router = APIRouter(prefix="/api", tags=["Classification"])

_REPOSITORY_NOT_FOUND = {"model": ErrorResponse, "description": "No repository exists with this id."}
_PROJECT_NOT_FOUND = {"model": ErrorResponse, "description": "No project exists with this id, or it has not been classified yet."}
_ENGAGEMENT_NOT_FOUND = {"model": ErrorResponse, "description": "No engagement exists with this id."}


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
    "/repositories/{repository_id}/classification-summary",
    response_model=ClassificationSummaryOut,
    summary="Get a repository's classification status counts",
    response_description="How many projects landed in each classification_status, per step-4-pattern-classification-against-catalog.md section 25.1.",
    operation_id="get_repository_classification_summary",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def get_repository_classification_summary(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    _get_repository(db, repository_id)
    return classification_service.classification_summary(db, repository_id)


@router.get(
    "/repositories/{repository_id}/classifications",
    response_model=ClassificationListOut,
    summary="List a repository's per-project classification results",
    response_description="One row per project, for the repository detail Classification section's table.",
    operation_id="list_repository_classifications",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def list_repository_classifications(
    repository_id: uuid.UUID,
    status: str | None = Query(None, description="Filter by classification_status, e.g. 'MATCHED'."),
    pattern_id: str | None = Query(None, description="Filter to projects whose primary_pattern_id matches this."),
    role: str | None = Query(None, description="Filter by project_role, e.g. 'APPLICATION'."),
    db: Session = Depends(get_db),
):
    _get_repository(db, repository_id)
    projects = classification_service.list_classifications(db, repository_id, status, pattern_id, role)
    return ClassificationListOut(repository_id=str(repository_id), projects=projects)


@router.get(
    "/projects/{project_id}/classification",
    response_model=ProjectClassificationDetailOut,
    summary="Get a project's full classification detail",
    response_description="Matched patterns plus near-miss patterns with their failed rules — what makes tuning possible.",
    operation_id="get_project_classification",
    responses={404: _PROJECT_NOT_FOUND},
)
def get_project_classification(project_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    `matches` holds every pattern this project actually matched — the
    selected primary plus any secondary capabilities. `near_misses` holds
    every pattern that was evaluated but did not match, with `failed_rules`
    naming exactly what was missing — the tuning input §25.4/Part I calls for.
    """
    detail = classification_service.project_classification_detail(db, project_id)
    if detail is None:
        raise error(404, f"Project '{project_id}' has not been classified", code="NOT_FOUND")
    return detail


@router.get(
    "/engagements/{engagement_id}/pattern-distribution",
    response_model=PatternDistributionOut,
    summary="Get an engagement's pattern distribution",
    response_description="Projects by primary pattern and secondary capability, confidence distribution, match and ambiguity rates — aggregated across every repository in the engagement.",
    operation_id="get_engagement_pattern_distribution",
    responses={404: _ENGAGEMENT_NOT_FOUND},
)
def get_engagement_pattern_distribution(engagement_id: str, db: Session = Depends(get_db)):
    """Label honestly: a count here means 'projects classified as X', never
    'X applications' — deployable-application aggregation is out of scope
    for step 4 (24-STEP-004-CLASSIFICATION.md Part I)."""
    _get_engagement(db, engagement_id)
    return classification_service.pattern_distribution(db, engagement_id)


@router.get(
    "/engagements/{engagement_id}/catalog-coverage",
    response_model=CatalogCoverageOut,
    summary="Get an engagement's catalog coverage",
    response_description="Registered vs referenced signals, patterns never matched, and patterns awaiting signals grouped by expected extractor — aggregated from the latest coverage report per repository in the engagement.",
    operation_id="get_engagement_catalog_coverage",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "No engagement exists with this id, or none of its repositories have been classified yet.",
        }
    },
)
def get_engagement_catalog_coverage(engagement_id: str, db: Session = Depends(get_db)):
    _get_engagement(db, engagement_id)
    coverage = classification_service.catalog_coverage(db, engagement_id)
    if coverage is None:
        raise error(
            404,
            f"No repository in engagement '{engagement_id}' has been classified yet",
            code="NO_COVERAGE_DATA",
        )
    return coverage
