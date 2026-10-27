"""The repository page's Tests section — 32-TEST-COVERAGE-ASSESSMENT.md
Part K, phase 1.

Rows come from the tables test-coverage-assessment writes (test_classes, test_mappings,
source_file_coverage, ci_maturity). The per-project figures and summary come
from the scan's result: a project's unit or integration percentage is
covered lines over instrumented lines across its files, which the per-file
percentages alone cannot reproduce. A reused scan points at the computed
scan whose result it reused.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.results.paging import PageOut, PageParams, page
from app.test_coverage.schemas import (
    CiMaturityOut,
    CoverageScanOut,
    ProjectCoverageOut,
    SourceFileOut,
    TestClassOut,
    TestCoverageOut,
    TestLinkOut,
    TestProjectOut,
)

router = APIRouter(prefix="/api", tags=["Test Coverage"])

PHASE_1_EXECUTION = (
    "No test is executed: execution is phase 3 of test-coverage-assessment (32-TEST-COVERAGE-ASSESSMENT Part F), behind two keys and opt-in per engagement. "
    "Coverage comes only from existing reports."
)


def _float(value) -> float | None:
    return None if value is None else float(value)


@router.get(
    "/repositories/{repository_id}/tests",
    response_model=TestCoverageOut,
    summary="Get a repository's tests, mapping, buckets, coverage and CI maturity",
    operation_id="get_repository_tests",
    responses={
        404: {"model": ErrorResponse, "description": "No repository exists with this id."},
        409: {"model": ErrorResponse, "description": "Test coverage (test-coverage-assessment) has not run yet for this repository."},
    },
)
def get_repository_tests(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    """test-coverage-assessment's latest result for the repository. 409 until it has run, so
    the UI can show an empty state naming the step."""
    scan, source, result = _scan(db, repository_id)

    mappings: dict[str, list[TestLinkOut]] = {}
    for row in db.query(models.TestMappingRow).filter(models.TestMappingRow.repository_id == repository_id):
        mappings.setdefault(row.source_file, []).append(TestLinkOut(
            test_file=row.test_file, test_class=row.test_class, test_type=row.test_type, method=row.mapping_method,
            confidence=float(row.confidence)))
    for links in mappings.values():
        links.sort(key=lambda link: (-link.confidence, link.test_file, link.test_class))

    files = [
        SourceFileOut(
            project_path=row.project_path, file_path=row.file_path, bucket=row.bucket, testable_members=row.testable_members,
            tests=mappings.get(row.file_path, []), coverage_source=row.coverage_source,
            line_pct=_float(row.line_pct), branch_pct=_float(row.branch_pct), not_measured_reason=row.not_measured_reason,
            unit_line_pct=_float(row.unit_line_pct), unit_not_measured_reason=row.unit_not_measured_reason,
            integration_line_pct=_float(row.integration_line_pct), integration_not_measured_reason=row.integration_not_measured_reason,
        )
        for row in db.query(models.SourceFileCoverage).filter(models.SourceFileCoverage.repository_id == repository_id)
        .order_by(models.SourceFileCoverage.file_path)
    ]
    classes = [
        TestClassOut(project_path=row.project_path, file_path=row.file_path, class_name=row.class_name, line_start=row.line_start,
                     test_type=row.test_type,
                     classification_reason=row.classification_reason, evidence=row.evidence, test_count=row.test_count)
        for row in db.query(models.TestClass).filter(models.TestClass.repository_id == repository_id)
        .order_by(models.TestClass.file_path, models.TestClass.class_name)
    ]
    ci = db.get(models.CiMaturity, repository_id)

    return TestCoverageOut(
        repository_id=str(repository_id),
        scan=_scan_out(scan, source),
        summary=result.get("summary", {}),
        ci_maturity=_ci_out(ci),
        test_projects=[
            TestProjectOut(project_path=p["projectPath"], reason=p["reason"], test_classes=p["testClasses"], test_classes_by_type=p["testClassesByType"])
            for p in result.get("testProjects", [])
        ],
        test_classes=classes,
        projects=[
            ProjectCoverageOut(
                project_path=p["projectPath"], files=p["files"], has_tests=p["hasTests"], missing_tests=p["missingTests"],
                no_testable_logic=p["noTestableLogic"], unit_line_pct=p.get("unitLinePct"), unit_not_measured_reason=p.get("unitNotMeasuredReason"),
                integration_line_pct=p.get("integrationLinePct"), integration_not_measured_reason=p.get("integrationNotMeasuredReason"),
            )
            for p in result.get("projects", [])
        ],
        source_files=files,
        coverage_reports=result.get("coverageReports", []),
        execution=PHASE_1_EXECUTION,
    )


def _scan(db: Session, repository_id: uuid.UUID):
    """The latest scan, the scan whose result it carries (itself, or the one it reused), and that result."""
    repo = db.get(models.Repository, repository_id)
    if repo is None or repo.deleted_at is not None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")
    scan = (
        db.query(models.CoverageScan)
        .filter(models.CoverageScan.repository_id == repository_id)
        # On a tie (one transaction), the scan that reused another came after it.
        .order_by(models.CoverageScan.scanned_at.desc(), models.CoverageScan.reused_from_scan_id.is_(None))
        .first()
    )
    if scan is None:
        raise error(409, "Test coverage (test-coverage-assessment) has not run yet for this repository.", code="NOT_SCANNED")
    source = db.get(models.CoverageScan, scan.reused_from_scan_id) if scan.reused_from_scan_id else scan
    return scan, source, (source.result if source is not None else None) or {}


def _scan_out(scan: models.CoverageScan, source: models.CoverageScan | None) -> CoverageScanOut:
    return CoverageScanOut(
        commit_sha=scan.commit_sha, cache_state=scan.cache_state, cache_note=scan.cache_note, scanned_at=scan.scanned_at,
        reused_from_scanned_at=source.scanned_at if scan.reused_from_scan_id and source is not None else None,
        report_sources=scan.report_sources,
    )


def _ci_out(ci: models.CiMaturity | None) -> CiMaturityOut | None:
    return CiMaturityOut(
        has_pipeline=ci.has_pipeline, runs_tests=ci.runs_tests, collects_coverage=ci.collects_coverage,
        publishes_coverage=ci.publishes_coverage, enforces_coverage_gate=ci.enforces_coverage_gate,
        pipelines=ci.pipelines, evidence=ci.evidence,
    ) if ci else None


# ---------- the Tests tab a page at a time (app.results.paging) ----------


class TestsSummaryOut(BaseModel):
    repository_id: str
    scan: CoverageScanOut
    summary: dict
    ci_maturity: CiMaturityOut | None
    counts: dict[str, int]
    not_measured_reasons: list[str]
    execution: str


_RESULT_LIST = """
    select e, n from coverage_scans c, jsonb_array_elements(coalesce(c.result->'{name}', '[]')) with ordinality t(e, n)
    where c.id = :scan
"""


@router.get(
    "/repositories/{repository_id}/tests/summary",
    response_model=TestsSummaryOut,
    summary="Get a repository's tests summary and CI maturity, without its lists",
    operation_id="get_repository_tests_summary",
    responses={404: {"model": ErrorResponse, "description": "No repository exists with this id."},
               409: {"model": ErrorResponse, "description": "Test coverage has not run yet for this repository."}},
)
def get_repository_tests_summary(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    """With how many items each list has, and every not-measured reason in the order the tables show them — per
    project (unit, then integration), then per source file — so a note keeps its number on every page."""
    scan, source, result = _scan(db, repository_id)
    projects = _RESULT_LIST.format(name="projects")
    reasons = db.execute(text(f"""
        select reason from (
            select e->>'unitNotMeasuredReason' as reason, n * 2 as k from ({projects}) p where e->>'unitLinePct' is null
            union all
            select e->>'integrationNotMeasuredReason', n * 2 + 1 from ({projects}) p where e->>'integrationLinePct' is null
            union all
            select not_measured_reason, 1000000000 + row_number() over (order by file_path)
            from source_file_coverage where repository_id = :r and line_pct is null
        ) x where reason is not null and reason <> '' group by reason order by min(k)
    """), {"scan": source.id, "r": repository_id}).scalars().all()
    counts = {
        "test_projects": len(result.get("testProjects", [])),
        "test_classes": db.query(models.TestClass).filter(models.TestClass.repository_id == repository_id).count(),
        "projects": len(result.get("projects", [])),
        "source_files": db.query(models.SourceFileCoverage).filter(models.SourceFileCoverage.repository_id == repository_id).count(),
    }
    return TestsSummaryOut(repository_id=str(repository_id), scan=_scan_out(scan, source), summary=result.get("summary", {}),
                           ci_maturity=_ci_out(db.get(models.CiMaturity, repository_id)), counts=counts,
                           not_measured_reasons=list(reasons), execution=PHASE_1_EXECUTION)


_PAGE_RESPONSES = {404: {"model": ErrorResponse, "description": "No repository exists with this id."},
                   409: {"model": ErrorResponse, "description": "Test coverage has not run yet for this repository."}}


@router.get("/repositories/{repository_id}/tests/test-projects", response_model=PageOut,
            summary="Get a page of a repository's test projects", operation_id="list_test_projects", responses=_PAGE_RESPONSES)
def list_test_projects(repository_id: uuid.UUID, paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as TestProjectOut, in the scan's order. The filter matches the project."""
    _, source, _ = _scan(db, repository_id)
    inner = _RESULT_LIST.format(name="testProjects")
    query = f"""
        select jsonb_build_object('project_path', e->>'projectPath', 'reason', e->>'reason', 'test_classes', e->'testClasses',
                                  'test_classes_by_type', e->'testClassesByType') as item,
               n as k, lower(e->>'projectPath') as search
        from ({inner}) t
    """
    return page(db, query, {"scan": source.id}, paging, order="k")


@router.get("/repositories/{repository_id}/tests/test-classes", response_model=PageOut,
            summary="Get a page of a repository's test classes", operation_id="list_test_classes", responses=_PAGE_RESPONSES)
def list_test_classes(repository_id: uuid.UUID, paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as TestClassOut, by file and class. The filter matches the class and the file."""
    _scan(db, repository_id)
    query = """
        select jsonb_build_object('project_path', project_path, 'file_path', file_path, 'class_name', class_name,
                                  'line_start', line_start, 'test_type', test_type,
                                  'classification_reason', classification_reason, 'evidence', evidence,
                                  'test_count', test_count) as item,
               file_path as k_file, class_name as k_class, lower(concat_ws(' ', class_name, file_path)) as search
        from test_classes where repository_id = :r
    """
    return page(db, query, {"r": repository_id}, paging, order="k_file, k_class")


@router.get("/repositories/{repository_id}/tests/projects", response_model=PageOut,
            summary="Get a page of a repository's coverage per project", operation_id="list_test_coverage_projects",
            responses=_PAGE_RESPONSES)
def list_test_coverage_projects(repository_id: uuid.UUID, paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as ProjectCoverageOut, in the scan's order. The filter matches the project."""
    _, source, _ = _scan(db, repository_id)
    inner = _RESULT_LIST.format(name="projects")
    query = f"""
        select jsonb_build_object('project_path', e->>'projectPath', 'files', e->'files', 'has_tests', e->'hasTests',
                                  'missing_tests', e->'missingTests', 'no_testable_logic', e->'noTestableLogic',
                                  'unit_line_pct', e->'unitLinePct', 'unit_not_measured_reason', e->'unitNotMeasuredReason',
                                  'integration_line_pct', e->'integrationLinePct',
                                  'integration_not_measured_reason', e->'integrationNotMeasuredReason') as item,
               n as k, lower(e->>'projectPath') as search
        from ({inner}) t
    """
    return page(db, query, {"scan": source.id}, paging, order="k")


@router.get("/repositories/{repository_id}/tests/source-files", response_model=PageOut,
            summary="Get a page of a repository's source files with their tests and coverage",
            operation_id="list_test_source_files", responses=_PAGE_RESPONSES)
def list_test_source_files(repository_id: uuid.UUID,
                           bucket: str | None = Query(None, description="has_tests, missing_tests or no_testable_logic; "
                                                                        "none: every file."),
                           paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as SourceFileOut, with the tests mapped to each, by file. The filter matches the file."""
    _scan(db, repository_id)
    query = """
        select jsonb_build_object('file_path', file_path) as item, file_path as k, lower(file_path) as search, bucket
        from source_file_coverage where repository_id = :r
    """
    result = page(db, query, {"r": repository_id, "bucket": bucket}, paging, order="k",
                  where="bucket = :bucket" if bucket else "true")
    paths = [i["file_path"] for i in result.items]
    if not paths:
        return result
    mappings: dict[str, list[TestLinkOut]] = {}
    for row in db.query(models.TestMappingRow).filter(models.TestMappingRow.repository_id == repository_id,
                                                      models.TestMappingRow.source_file.in_(paths)):
        mappings.setdefault(row.source_file, []).append(TestLinkOut(
            test_file=row.test_file, test_class=row.test_class, test_type=row.test_type, method=row.mapping_method,
            confidence=float(row.confidence)))
    for links in mappings.values():
        links.sort(key=lambda link: (-link.confidence, link.test_file, link.test_class))
    rows = {r.file_path: r for r in db.query(models.SourceFileCoverage).filter(
        models.SourceFileCoverage.repository_id == repository_id, models.SourceFileCoverage.file_path.in_(paths))}
    items = [SourceFileOut(
        project_path=row.project_path, file_path=row.file_path, bucket=row.bucket, testable_members=row.testable_members,
        tests=mappings.get(row.file_path, []), coverage_source=row.coverage_source,
        line_pct=_float(row.line_pct), branch_pct=_float(row.branch_pct), not_measured_reason=row.not_measured_reason,
        unit_line_pct=_float(row.unit_line_pct), unit_not_measured_reason=row.unit_not_measured_reason,
        integration_line_pct=_float(row.integration_line_pct), integration_not_measured_reason=row.integration_not_measured_reason,
    ).model_dump(mode="json") for row in (rows[p] for p in paths)]
    return PageOut(total=result.total, matching=result.matching, offset=result.offset, items=items)

