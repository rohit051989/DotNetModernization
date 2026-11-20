"""A failed discovery run (app.results.last_scan): the repository page is told when, at which step and which steps'
results are older, and conversion preparation refuses to run on a mix of new and older results.

Runs in this test run's own schema (tests/__init__.py). stdlib unittest, as the other database tests.
"""
import datetime
import tempfile
import unittest
import uuid
from pathlib import Path

from sqlalchemy import text

from app import models
from app.db import SessionLocal
from app.engine import convert
from app.results import last_scan, views
from app.steps import conversion_preparation
from app.workflow.definition.model import JobDefinitionFile
from tests.support import TEST_ENGAGEMENT_ID, CommittedTestEngagement

T0 = datetime.datetime(2026, 11, 19, 13, 36, tzinfo=datetime.timezone.utc)
T1 = datetime.datetime(2026, 11, 19, 20, 6, tzinfo=datetime.timezone.utc)
FAILURE = ("ArtifactSchemaValidationException: Artifact failed JSON Schema validation:\n"
           "/projects/0/feeds/0/declaredIn: enum")


class FailedScan(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.engagement = CommittedTestEngagement(self.db)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tag = uuid.uuid4().hex[:6]
        self.repo = models.Repository(engagement_id=TEST_ENGAGEMENT_ID, name=f"Shop {tag}", slug=f"shop-{tag}",
                                      source_type="local_path", local_path=str(Path(self.tmp.name) / "shop"),
                                      local_path_normalised=str(Path(self.tmp.name) / "shop").lower(),
                                      root_folder_name="shop", ingest_status="scanned")
        self.db.add(self.repo)
        self.db.commit()
        self.definition = self.db.query(models.WfJobDefinition).filter_by(
            job_name=last_scan.DISCOVERY, is_active=True).one()
        self.flow = last_scan._steps(JobDefinitionFile.model_validate(self.definition.definition).flow)

    def tearDown(self):
        self.db.rollback()
        executions = [e for (e,) in self.db.execute(text(
            "select j.id from wf_job_executions j join wf_job_instances i on i.id = j.job_instance_id "
            "where i.parameters->>'repository_id' = :r"), {"r": str(self.repo.id)})]
        self.db.execute(text("delete from wf_step_executions where job_execution_id = any(:e)"), {"e": executions})
        self.db.execute(text("delete from wf_job_executions where id = any(:e)"), {"e": executions})
        self.db.execute(text("delete from wf_job_instances where parameters->>'repository_id' = :r"), {"r": str(self.repo.id)})
        self.db.execute(text("delete from repositories where id = :r"), {"r": self.repo.id})
        self.db.commit()
        self.engagement.remove()
        self.db.close()

    def run_of(self, at: datetime.datetime, fail_at: str | None = None, status: str | None = None):
        """A discovery run at `at`: every step up to `fail_at` completed, `fail_at` failed, the rest never ran."""
        instance = models.WfJobInstance(job_name=last_scan.DISCOVERY, job_key=uuid.uuid4().hex,
                                        parameters={"engagement_id": TEST_ENGAGEMENT_ID, "repository_id": str(self.repo.id)})
        self.db.add(instance)
        self.db.flush()
        execution = models.WfJobExecution(job_instance_id=instance.id, job_definition_id=self.definition.id,
                                          execution_number=1, engine_version="test", created_at=at, started_at=at,
                                          ended_at=at + datetime.timedelta(minutes=5),
                                          batch_status=status or ("FAILED" if fail_at else "COMPLETED"),
                                          exit_status=status or ("FAILED" if fail_at else "COMPLETED"))
        self.db.add(execution)
        self.db.flush()
        for i, step in enumerate(self.flow):
            ended = at + datetime.timedelta(seconds=i + 1)
            if step == fail_at:
                self.db.add(models.WfStepExecution(job_execution_id=execution.id, step_name=step, step_version="1",
                                                   batch_status="FAILED", exit_status="FAILED", exit_message=FAILURE,
                                                   started_at=ended, ended_at=ended))
                break
            self.db.add(models.WfStepExecution(job_execution_id=execution.id, step_name=step, step_version="1",
                                               batch_status="COMPLETED", exit_status="COMPLETED",
                                               started_at=ended, ended_at=ended))
        self.db.commit()
        return execution

    def test_a_completed_latest_run_says_nothing(self):
        self.run_of(T0)
        self.assertIsNone(last_scan.failed_scan(self.db, self.repo.id))
        self.assertIsNone(views.get_repository_results(self.repo.id, self.db).failed_scan)
        self.assertIsNone(last_scan.refusal(self.db, self.repo.id))

    def test_a_failed_run_names_the_step_when_and_the_date_of_each_older_result(self):
        self.run_of(T0)
        failed = self.run_of(T1, fail_at="dependency-assessment")

        out = views.get_repository_results(self.repo.id, self.db).failed_scan
        self.assertEqual((out.job_execution_id, out.status, out.failed_step), (failed.id, "FAILED", "dependency-assessment"))
        self.assertEqual(out.message, "ArtifactSchemaValidationException: Artifact failed JSON Schema validation:")
        after = self.flow[self.flow.index("dependency-assessment"):]
        self.assertEqual(list(out.results_from), after)
        # The older results each of those tabs shows are the earlier run's; the steps before the failure are new.
        self.assertTrue(all(T0 <= at < T1 for at in out.results_from.values()), out.results_from)
        self.assertNotIn("solution-discovery", out.results_from)
        self.assertNotIn("application-fingerprinting", out.results_from)

    def test_a_step_that_never_completed_has_no_older_results(self):
        self.run_of(T1, fail_at="dependency-assessment")
        self.assertIsNone(last_scan.failed_scan(self.db, self.repo.id)["results_from"]["dependency-assessment"])

    def test_a_stopped_run_counts_and_a_later_completed_run_clears_it(self):
        self.run_of(T0, status="STOPPED")
        self.assertEqual(last_scan.failed_scan(self.db, self.repo.id)["status"], "STOPPED")
        self.run_of(T1)
        self.assertIsNone(last_scan.failed_scan(self.db, self.repo.id))

    def test_preparation_refuses_a_mix_of_new_and_older_results_and_says_why(self):
        self.run_of(T0)
        self.run_of(T1, fail_at="dependency-assessment")
        with self.assertRaises(convert.ResultsMixed) as refused:
            convert.prepare(self.db, TEST_ENGAGEMENT_ID, self.repo.slug)
        message = str(refused.exception)
        self.assertIn("failed at dependency-assessment on 2026-11-19 20:06 UTC", message)
        self.assertIn("dependency-hierarchy", message)
        self.assertIn("rescan", message)
        self.assertNotIn("conversion-preparation", message)
        # Refused before anything was made: no conversion folder.
        self.assertFalse(convert.conversions_dir(TEST_ENGAGEMENT_ID, self.repo.slug).exists())
        # The discovery job's own step records the sentence as it is, not cut short.
        self.assertEqual(conversion_preparation.problem(refused.exception), (message, []))


if __name__ == "__main__":
    unittest.main()
