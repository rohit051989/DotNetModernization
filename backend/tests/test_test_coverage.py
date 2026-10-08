"""Step 8's Tests section API and its tables — 32-TEST-COVERAGE-ASSESSMENT.md
Parts E1, I, J and K, phase 1.

Hermetic: a fixture repository and scan rows inside one rolled-back
transaction. The step itself is tested in the .NET solution
(tests/Fingerprinting.Tests/TestCoverageTests.cs).

Run from backend/:  python -m unittest tests.test_test_coverage -v
"""

import unittest
import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app import models
from app.routers import test_coverage
from tests.test_item_detection import DetectionTestCase

RESULT = {
    "summary": {"testClasses": 1, "testMethods": 2},
    "testProjects": [{"projectPath": "tests/T/T.csproj", "reason": "test package xunit", "testClasses": 1,
                      "testClassesByType": {"unit": 1, "integration": 0, "functional": 0, "smoke": 0, "unclassified": 0}}],
    "projects": [{"projectPath": "src/S/S.csproj", "files": 1, "hasTests": 1, "missingTests": 0, "noTestableLogic": 0,
                  "unitLinePct": None, "unitNotMeasuredReason": "not measured — no unit coverage report",
                  "integrationLinePct": None, "integrationNotMeasuredReason": "not measured — integration tests are not executed during discovery"}],
    "coverageReports": [],
}


class TestCoverageApiTests(DetectionTestCase):
    def scan(self, **fields):
        row = models.CoverageScan(repository_id=self.repo.id, cache_key="k", result_checksum="c", **fields)
        self.db.add(row)
        self.db.flush()
        return row

    def file_row(self, **fields):
        values = dict(repository_id=self.repo.id, project_path="src/S/S.csproj", file_path="src/S/A.cs", bucket="has_tests",
                      testable_members=1, coverage_source="not_measured", not_measured_reason="not measured — no report",
                      unit_not_measured_reason="no unit report", integration_not_measured_reason="not executed")
        values.update(fields)
        row = models.SourceFileCoverage(**values)
        self.db.add(row)
        self.db.flush()
        return row

    def test_before_step_8_has_run_it_is_409(self):
        with self.assertRaises(HTTPException) as raised:
            test_coverage.get_repository_tests(self.repo.id, db=self.db)
        self.assertEqual(raised.exception.status_code, 409)

    def test_a_reused_scan_serves_the_computed_result_it_reused(self):
        computed = self.scan(commit_sha="abc", cache_state="computed", result=RESULT)
        self.scan(commit_sha="abc", cache_state="reused", reused_from_scan_id=computed.id, cache_note="reused")
        self.file_row()
        self.db.add(models.TestMappingRow(repository_id=self.repo.id, source_file="src/S/A.cs", production_type="S.A", test_file="tests/T/ATests.cs",
                                          test_class="T.ATests", test_type="unit", mapping_method="type_reference+naming", confidence=0.95))
        self.db.add(models.CiMaturity(repository_id=self.repo.id, has_pipeline=True, runs_tests=True, collects_coverage=False,
                                      publishes_coverage=False, enforces_coverage_gate=False))
        self.db.flush()

        out = test_coverage.get_repository_tests(self.repo.id, db=self.db)
        self.assertEqual((out.scan.cache_state, out.scan.reused_from_scanned_at), ("reused", computed.scanned_at))
        self.assertEqual(out.projects[0].unit_not_measured_reason, "not measured — no unit coverage report")
        self.assertIsNone(out.projects[0].unit_line_pct)
        self.assertEqual([t.test_file for t in out.source_files[0].tests], ["tests/T/ATests.cs"])
        self.assertTrue(out.ci_maturity.runs_tests)
        self.assertIn("No test is executed", out.execution)

    def test_the_database_refuses_unknown_coverage_stored_as_a_number(self):
        # Part E1: not measured never shows as a percentage — not even 0.
        with self.assertRaises(IntegrityError):
            with self.db.begin_nested():
                self.file_row(line_pct=0)

    def test_the_database_refuses_not_measured_without_a_reason(self):
        with self.assertRaises(IntegrityError):
            with self.db.begin_nested():
                self.file_row(not_measured_reason=None)

    def test_a_measured_file_has_a_percentage_and_no_reason(self):
        row = self.file_row(coverage_source="existing_report", line_pct=62.5, not_measured_reason=None)
        self.assertEqual(float(row.line_pct), 62.5)


if __name__ == "__main__":
    unittest.main()
