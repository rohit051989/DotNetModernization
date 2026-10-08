"""The repository page's Tests section — 32-STEP-008-TEST-COVERAGE.md
Part K, phase 1.

Rows come from the tables step 8 writes (test_classes, test_mappings,
source_file_coverage, ci_maturity). The per-project figures and summary come
from the scan's result: a project's unit or integration percentage is
covered lines over instrumented lines across its files, which the per-file
percentages alone cannot reproduce. A reused scan points at the computed
scan whose result it reused.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
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
    "No test is executed: execution is phase 3 of step 8 (32-STEP-008 Part F), behind two keys and opt-in per engagement. "
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
        409: {"model": ErrorResponse, "description": "Test coverage (lifecycle step 8) has not run yet for this repository."},
    },
)
def get_repository_tests(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    """Step 8's latest result for the repository. 409 until it has run, so
    the UI can show an empty state naming the step."""
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
        raise error(409, "Test coverage (step 8) has not run yet for this repository.", code="NOT_SCANNED")
    source = db.get(models.CoverageScan, scan.reused_from_scan_id) if scan.reused_from_scan_id else scan
    result = (source.result if source is not None else None) or {}

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
        scan=CoverageScanOut(
            commit_sha=scan.commit_sha, cache_state=scan.cache_state, cache_note=scan.cache_note, scanned_at=scan.scanned_at,
            reused_from_scanned_at=source.scanned_at if scan.reused_from_scan_id and source is not None else None,
            report_sources=scan.report_sources,
        ),
        summary=result.get("summary", {}),
        ci_maturity=CiMaturityOut(
            has_pipeline=ci.has_pipeline, runs_tests=ci.runs_tests, collects_coverage=ci.collects_coverage,
            publishes_coverage=ci.publishes_coverage, enforces_coverage_gate=ci.enforces_coverage_gate,
            pipelines=ci.pipelines, evidence=ci.evidence,
        ) if ci else None,
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
