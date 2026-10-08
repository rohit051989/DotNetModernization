"""Response shapes for the repository page's Tests section —
32-TEST-COVERAGE-ASSESSMENT.md Part K, phase 1."""

import datetime
from typing import Literal

from pydantic import BaseModel, Field

TestType = Literal["unit", "integration", "functional", "smoke", "unclassified"]
Bucket = Literal["has_tests", "missing_tests", "no_testable_logic"]


class CoverageScanOut(BaseModel):
    commit_sha: str | None
    cache_state: Literal["computed", "reused", "no_commit", "uncommitted_changes"]
    cache_note: str | None
    scanned_at: datetime.datetime
    reused_from_scanned_at: datetime.datetime | None = Field(description="When the reused result was computed.")
    report_sources: list[dict]


class CiMaturityOut(BaseModel):
    has_pipeline: bool
    runs_tests: bool
    collects_coverage: bool
    publishes_coverage: bool
    enforces_coverage_gate: bool
    pipelines: list[dict]
    evidence: list[dict]


class TestProjectOut(BaseModel):
    project_path: str
    reason: str
    test_classes: int
    test_classes_by_type: dict[str, int]


class TestClassOut(BaseModel):
    project_path: str
    file_path: str
    class_name: str
    line_start: int
    test_type: TestType
    classification_reason: str
    evidence: list[dict]
    test_count: int


class ProjectCoverageOut(BaseModel):
    project_path: str
    files: int
    has_tests: int
    missing_tests: int
    no_testable_logic: int
    unit_line_pct: float | None
    unit_not_measured_reason: str | None
    integration_line_pct: float | None
    integration_not_measured_reason: str | None


class TestLinkOut(BaseModel):
    test_file: str
    test_class: str
    test_type: TestType
    method: str
    confidence: float


class SourceFileOut(BaseModel):
    project_path: str
    file_path: str
    bucket: Bucket
    testable_members: int
    tests: list[TestLinkOut]
    coverage_source: Literal["existing_report", "executed", "not_measured"]
    line_pct: float | None
    branch_pct: float | None
    not_measured_reason: str | None = Field(description="Always set when coverage_source is not_measured: unknown is never 0%.")
    unit_line_pct: float | None
    unit_not_measured_reason: str | None
    integration_line_pct: float | None
    integration_not_measured_reason: str | None


class TestCoverageOut(BaseModel):
    repository_id: str
    scan: CoverageScanOut
    summary: dict
    ci_maturity: CiMaturityOut | None
    test_projects: list[TestProjectOut]
    test_classes: list[TestClassOut]
    projects: list[ProjectCoverageOut]
    source_files: list[SourceFileOut]
    coverage_reports: list[dict]
    execution: str = Field(description="Phase 1: no test is executed (Part L). Part F's decisions arrive with phase 3.")
