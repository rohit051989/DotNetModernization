"""Read-only query logic for step 2's discovery results — see
19-SOLUTION-DISCOVERY.md Part I. Nothing here mutates; solution-
discovery (the standalone script) owns every row in these tables.
"""

import uuid

from sqlalchemy.orm import Session

from app import models


def get_structure(db: Session, repository_id: uuid.UUID) -> models.RepositoryStructure | None:
    return db.get(models.RepositoryStructure, repository_id)


def list_solutions(db: Session, repository_id: uuid.UUID) -> list[dict]:
    """Solutions with their member projects, each resolved to a relative
    path where possible (Part I: 'solutions with their projects')."""
    solutions = (
        db.query(models.Solution)
        .filter(models.Solution.repository_id == repository_id)
        .order_by(models.Solution.relative_path)
        .all()
    )
    if not solutions:
        return []

    solution_ids = [s.id for s in solutions]
    members = (
        db.query(models.SolutionProject)
        .filter(models.SolutionProject.solution_id.in_(solution_ids))
        .order_by(models.SolutionProject.raw_path)
        .all()
    )
    project_ids = {m.project_id for m in members if m.project_id is not None}
    relpath_by_project = {
        p.id: p.relative_path
        for p in db.query(models.Project).filter(models.Project.id.in_(project_ids))
    } if project_ids else {}

    members_by_solution: dict[uuid.UUID, list] = {}
    for member in members:
        members_by_solution.setdefault(member.solution_id, []).append(
            {
                "raw_path": member.raw_path,
                "project_id": member.project_id,
                "relative_path": relpath_by_project.get(member.project_id),
                "project_guid": member.project_guid,
                "project_type_guid": member.project_type_guid,
                "solution_folder": member.solution_folder,
                "resolution_status": member.resolution_status,
            }
        )

    return [
        {
            "id": s.id,
            "name": s.name,
            "relative_path": s.relative_path,
            "format_version": s.format_version,
            "visual_studio_version": s.visual_studio_version,
            "minimum_vs_version": s.minimum_vs_version,
            "project_count": s.project_count,
            "resolved_project_count": s.resolved_project_count,
            "missing_project_count": s.missing_project_count,
            "solution_folder_count": s.solution_folder_count,
            "shared_project_count": s.shared_project_count,
            "parse_status": s.parse_status,
            "parse_error": s.parse_error,
            "projects": members_by_solution.get(s.id, []),
        }
        for s in solutions
    ]


def list_projects(
    db: Session,
    repository_id: uuid.UUID,
    framework_family: str | None = None,
    project_format: str | None = None,
    standalone: bool | None = None,
    q: str | None = None,
) -> list[models.Project]:
    query = db.query(models.Project).filter(models.Project.repository_id == repository_id)
    if framework_family:
        query = query.filter(models.Project.framework_family == framework_family)
    if project_format:
        query = query.filter(models.Project.project_format == project_format)
    if standalone is not None:
        query = query.filter(models.Project.is_standalone == standalone)
    if q:
        like = f"%{q}%"
        query = query.filter(models.Project.name.ilike(like) | models.Project.relative_path.ilike(like))
    return query.order_by(models.Project.relative_path).all()


def list_project_references(db: Session, repository_id: uuid.UUID) -> list[dict]:
    projects = {
        p.id: p.relative_path
        for p in db.query(models.Project).filter(models.Project.repository_id == repository_id)
    }
    if not projects:
        return []
    references = (
        db.query(models.ProjectReference)
        .filter(models.ProjectReference.source_project_id.in_(projects.keys()))
        .order_by(models.ProjectReference.raw_path)
        .all()
    )
    return [
        {
            "id": r.id,
            "source_project_id": r.source_project_id,
            "source_relative_path": projects.get(r.source_project_id),
            "referenced_project_id": r.referenced_project_id,
            "referenced_relative_path": projects.get(r.referenced_project_id) if r.referenced_project_id else None,
            "raw_path": r.raw_path,
            "resolution_status": r.resolution_status,
            "is_cross_solution": r.is_cross_solution,
        }
        for r in references
    ]


def list_repository_artifacts(
    db: Session, repository_id: uuid.UUID, category: str | None = None
) -> list[models.RepositoryArtifact]:
    query = db.query(models.RepositoryArtifact).filter(models.RepositoryArtifact.repository_id == repository_id)
    if category:
        query = query.filter(models.RepositoryArtifact.category == category)
    return query.order_by(models.RepositoryArtifact.relative_path).all()


def get_project_detail(db: Session, project_id: uuid.UUID) -> dict | None:
    project = db.get(models.Project, project_id)
    if project is None:
        return None

    packages = (
        db.query(models.ProjectPackage)
        .filter(models.ProjectPackage.project_id == project_id)
        .order_by(models.ProjectPackage.declaration_source, models.ProjectPackage.package_name)
        .all()
    )
    outgoing = (
        db.query(models.ProjectReference)
        .filter(models.ProjectReference.source_project_id == project_id)
        .order_by(models.ProjectReference.raw_path)
        .all()
    )
    incoming = (
        db.query(models.ProjectReference)
        .filter(models.ProjectReference.referenced_project_id == project_id)
        .order_by(models.ProjectReference.raw_path)
        .all()
    )

    related_ids = {r.source_project_id for r in incoming} | {r.referenced_project_id for r in outgoing if r.referenced_project_id}
    related_ids.add(project_id)
    relpath_by_project = {
        p.id: p.relative_path for p in db.query(models.Project).filter(models.Project.id.in_(related_ids))
    }

    def _reference_out(r: models.ProjectReference) -> dict:
        return {
            "id": r.id,
            "source_project_id": r.source_project_id,
            "source_relative_path": relpath_by_project.get(r.source_project_id),
            "referenced_project_id": r.referenced_project_id,
            "referenced_relative_path": relpath_by_project.get(r.referenced_project_id) if r.referenced_project_id else None,
            "raw_path": r.raw_path,
            "resolution_status": r.resolution_status,
            "is_cross_solution": r.is_cross_solution,
        }

    return {
        "id": project.id,
        "repository_id": project.repository_id,
        "name": project.name,
        "relative_path": project.relative_path,
        "extension": project.extension,
        "structural_type": project.structural_type,
        "project_format": project.project_format,
        "language": project.language,
        "assembly_name": project.assembly_name,
        "root_namespace": project.root_namespace,
        "output_type": project.output_type,
        "target_framework_raw": project.target_framework_raw,
        "target_frameworks_raw": project.target_frameworks_raw,
        "framework_family": project.framework_family,
        "framework_version": project.framework_version,
        "is_multi_targeting": project.is_multi_targeting,
        "solution_membership_count": project.solution_membership_count,
        "is_standalone": project.is_standalone,
        "project_reference_count": project.project_reference_count,
        "package_reference_count": project.package_reference_count,
        "package_management_style": project.package_management_style,
        "has_packages_config": project.has_packages_config,
        "parse_status": project.parse_status,
        "parse_warnings": project.parse_warnings or [],
        "packages": packages,
        "project_references": [_reference_out(r) for r in outgoing],
        "referenced_by": [_reference_out(r) for r in incoming],
    }


def get_engagement_structure_summary(db: Session, engagement_id: str) -> dict:
    """Portfolio rollup for the dashboard — Part I: 'GET
    /api/engagements/{eid}/structure-summary'. Sums repository_structure
    across every non-deleted repository in the engagement that has been
    scanned by solution-discovery."""
    rows = (
        db.query(models.RepositoryStructure)
        .join(models.Repository, models.Repository.id == models.RepositoryStructure.repository_id)
        .filter(models.Repository.engagement_id == engagement_id, models.Repository.deleted_at.is_(None))
        .all()
    )

    framework_families: dict[str, int] = {}
    for row in rows:
        for family, count in (row.framework_families or {}).items():
            framework_families[family] = framework_families.get(family, 0) + count

    return {
        "engagement_id": engagement_id,
        "repositories_scanned": len(rows),
        "solution_count": sum(r.solution_count or 0 for r in rows),
        "project_file_count": sum(r.project_file_count or 0 for r in rows),
        "standalone_project_count": sum(r.standalone_project_count or 0 for r in rows),
        "unresolved_reference_count": sum(r.unresolved_reference_count or 0 for r in rows),
        "legacy_project_count": sum(r.legacy_project_count or 0 for r in rows),
        "sdk_project_count": sum(r.sdk_project_count or 0 for r in rows),
        "framework_families": framework_families,
    }
