"""The engine refuses an artifact whose reported version is not the version the file declares (release 7;
app/workflow/adapters/base.py). dependency-assessment once wrote 1.6.0 and reported 1.5.0; the step would now fail.
test_platform_scale checks the same over every registered step in real runs.

Uses stdlib unittest, same rationale as test_repository_ingest.py.
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.workflow.adapters.base import StepAdapter, compute_checksum, declared_version
from app.workflow.contract import StepContext, StepOutput, StepResult


class _Writes(StepAdapter):
    """An adapter that writes one artifact and reports it at a given version."""

    def __init__(self, path: Path, body: dict, reported: str):
        self.path, self.body, self.reported = path, body, reported

    def _invoke(self, context: StepContext) -> StepResult:
        self.path.write_text(json.dumps(self.body), encoding="utf-8")
        uri = self.path.as_uri()
        return StepResult(exit_status="COMPLETED", outputs=[
            StepOutput(artifact_type="dependency-assessment", artifact_version=self.reported, uri=uri, checksum=compute_checksum(uri))])


class ArtifactVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "dependency-assessment.json"
        self.context = StepContext(step_name="s", step_version="1.0.0", job_name="j", job_execution_id="1", step_execution_id="2",
                                   working_dir=self.tmp.name, output_dir=self.tmp.name)

    def test_a_reported_version_other_than_the_written_one_fails_the_step(self):
        result = _Writes(self.path, {"artifactVersion": "1.6.0"}, reported="1.5.0").run(self.context)
        self.assertEqual(result.exit_status, "FAILED")
        self.assertEqual(result.outputs, [])
        self.assertIn("reported 1.5.0, the file declares 1.6.0", result.exit_message)
        self.assertEqual([d.code for d in result.diagnostics], ["ARTIFACT_VERSION_MISMATCH"])

    def test_the_written_version_reported_passes(self):
        result = _Writes(self.path, {"artifact_version": "1.6.0"}, reported="1.6.0").run(self.context)
        self.assertEqual((result.exit_status, len(result.outputs)), ("COMPLETED", 1))

    def test_a_sarif_log_declares_its_version_as_version(self):
        path = Path(self.tmp.name) / "x.sarif"
        path.write_text(json.dumps({"version": "2.1.0", "runs": []}), encoding="utf-8")
        self.assertEqual(declared_version(path.as_uri()), "2.1.0")
