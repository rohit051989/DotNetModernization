"""Read-only endpoints over step 2's (solution-discovery) results. See
19-SOLUTION-DISCOVERY.md Part I and 18-API-CONVENTIONS.md.

Nothing here mutates — solution-discovery (the standalone script under
steps/step-002-solution-discovery/) owns every row these routes read.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.results.paging import PageOut, PageParams, page
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
def get_repository_structure(
    repository_id: uuid.UUID,
    warnings: bool = Query(True, description="false: leave parse_warnings out (parse_warning_count still says how many); "
                                             "the UI pages them from /structure/warnings."),
    db: Session = Depends(get_db),
):
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
    out = RepositoryStructureOut.model_validate(structure)
    out.parse_warning_count = len(out.parse_warnings)
    if not warnings:
        out.parse_warnings = []
    return out


# ---------- the Projects tab's lists, a page at a time (app.results.paging) ----------


@router.get(
    "/repositories/{repository_id}/structure/warnings",
    response_model=PageOut,
    summary="Get a page of a repository's discovery warnings",
    operation_id="list_structure_warnings",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def list_structure_warnings(repository_id: uuid.UUID, paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items: {path, warning}, in the scan's order. The filter matches the path."""
    _get_repository(db, repository_id)
    source = """
        select w as item, n as k, lower(w->>'path') as search
        from repository_structure s, jsonb_array_elements(coalesce(s.parse_warnings, '[]')) with ordinality t(w, n)
        where s.repository_id = :r
    """
    return page(db, source, {"r": repository_id}, paging, order="k")


@router.get(
    "/repositories/{repository_id}/solutions/page",
    response_model=PageOut,
    summary="Get a page of a repository's solutions, without their members",
    operation_id="list_repository_solutions_page",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def list_repository_solutions_page(repository_id: uuid.UUID, paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as SolutionOut with `projects` empty and `member_count` set: the members come a page at a time from
    /solutions/{id}/members. By path; the filter matches the name and the path."""
    _get_repository(db, repository_id)
    source = """
        select jsonb_build_object('id', s.id, 'name', s.name, 'relative_path', s.relative_path,
                                  'format_version', s.format_version, 'visual_studio_version', s.visual_studio_version,
                                  'minimum_vs_version', s.minimum_vs_version, 'project_count', s.project_count,
                                  'resolved_project_count', s.resolved_project_count,
                                  'missing_project_count', s.missing_project_count,
                                  'solution_folder_count', s.solution_folder_count,
                                  'shared_project_count', s.shared_project_count, 'parse_status', s.parse_status,
                                  'parse_error', s.parse_error, 'projects', '[]'::jsonb,
                                  'member_count', (select count(*) from solution_projects m where m.solution_id = s.id)) as item,
               s.relative_path as k, lower(concat_ws(' ', s.name, s.relative_path)) as search
        from solutions s where s.repository_id = :r
    """
    return page(db, source, {"r": repository_id}, paging, order='k collate "C"')


@router.get(
    "/repositories/{repository_id}/solutions/{solution_id}/members",
    response_model=PageOut,
    summary="Get a page of one solution's member projects",
    operation_id="list_solution_members",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def list_solution_members(repository_id: uuid.UUID, solution_id: uuid.UUID, paging: PageParams = Depends(),
                          db: Session = Depends(get_db)):
    """Items as SolutionProjectMemberOut, by raw path. The filter matches the resolved path, or the raw one."""
    _get_repository(db, repository_id)
    source = """
        select jsonb_build_object('raw_path', m.raw_path, 'project_id', m.project_id, 'relative_path', p.relative_path,
                                  'project_guid', m.project_guid, 'project_type_guid', m.project_type_guid,
                                  'solution_folder', m.solution_folder, 'resolution_status', m.resolution_status) as item,
               m.raw_path as k, lower(coalesce(p.relative_path, m.raw_path)) as search
        from solution_projects m
        join solutions s on s.id = m.solution_id
        left join projects p on p.id = m.project_id
        where s.repository_id = :r and m.solution_id = :s
    """
    return page(db, source, {"r": repository_id, "s": solution_id}, paging, order='k collate "C"')


@router.get(
    "/repositories/{repository_id}/projects/page",
    response_model=PageOut,
    summary="Get a page of a repository's projects",
    operation_id="list_repository_projects_page",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def list_repository_projects_page(
    repository_id: uuid.UUID,
    standalone: bool | None = Query(None, description="Only projects with (false) or without (true) solution membership."),
    paging: PageParams = Depends(),
    db: Session = Depends(get_db),
):
    """Items as ProjectSummaryOut, by path. The filter matches the path."""
    _get_repository(db, repository_id)
    source = """
        select jsonb_build_object('id', p.id, 'repository_id', p.repository_id, 'name', p.name,
                                  'relative_path', p.relative_path, 'extension', p.extension,
                                  'structural_type', p.structural_type, 'project_format', p.project_format,
                                  'language', p.language, 'framework_family', p.framework_family,
                                  'framework_version', p.framework_version, 'is_multi_targeting', p.is_multi_targeting,
                                  'solution_membership_count', p.solution_membership_count, 'is_standalone', p.is_standalone,
                                  'project_reference_count', p.project_reference_count,
                                  'package_reference_count', p.package_reference_count,
                                  'package_management_style', p.package_management_style,
                                  'has_packages_config', p.has_packages_config, 'parse_status', p.parse_status) as item,
               p.relative_path as k, lower(p.relative_path) as search, p.is_standalone
        from projects p where p.repository_id = :r
    """
    where = "true" if standalone is None else ("is_standalone" if standalone else "not is_standalone")
    return page(db, source, {"r": repository_id}, paging, order='k collate "C"', where=where)


@router.get(
    "/repositories/{repository_id}/artifacts/page",
    response_model=PageOut,
    summary="Get a page of a repository's supporting artifacts",
    operation_id="list_repository_artifacts_page",
    responses={404: _REPOSITORY_NOT_FOUND},
)
def list_repository_artifacts_page(repository_id: uuid.UUID, paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as RepositoryArtifactOut, by path. The filter matches the path. The counts per category are the
    structure's artifact_counts."""
    _get_repository(db, repository_id)
    source = """
        select jsonb_build_object('id', a.id, 'category', a.category, 'relative_path', a.relative_path,
                                  'file_name', a.file_name) as item,
               a.relative_path as k, lower(a.relative_path) as search
        from repository_artifacts a where a.repository_id = :r
    """
    return page(db, source, {"r": repository_id}, paging, order='k collate "C"')


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
