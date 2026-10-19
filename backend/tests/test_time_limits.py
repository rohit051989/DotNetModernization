"""Step time limits, progress, and stopping an in-process step (rbc-release-5).

Run with:
    python -m unittest tests.test_time_limits
"""
import json
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.db import engine
from app.workflow import progress, time_limits
from app.workflow.adapters.python_adapter import PythonAdapter
from app.workflow.contract import StepContext, StepResult
from tests.support import TEST_ENGAGEMENT_ID, ensure_test_engagement

STEP = "outbound-invocation-inventory"


class EffectiveLimits(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")
        ensure_test_engagement(self.db)
        tag = uuid.uuid4().hex[:8]
        self.repo = models.Repository(
            engagement_id=TEST_ENGAGEMENT_ID, name=f"t-{tag}", root_folder_name=f"t-{tag}", slug=f"t-{tag}",
            local_path=f"C:/t-{tag}", local_path_normalised=f"c:/t-{tag}", source_type="local_path", ingest_status="scanned")
        self.db.add(self.repo)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.connection.close()

    def test_the_defaults_apply_when_nothing_overrides_them(self):
        e = time_limits.effective(self.db, "a-step-nobody-configured", self.repo.id)
        self.assertEqual((e["timeout_seconds"], e["stall_seconds"]), (settings.step_timeout_seconds, settings.step_stall_seconds))
        self.assertEqual(e["timeout_from"], "default (STEP_TIMEOUT_SECONDS)")

    def test_the_most_specific_override_wins_and_each_limit_falls_through_on_its_own(self):
        time_limits.set_limit(self.db, STEP, None, 7200, None)                 # this step, every repository
        time_limits.set_limit(self.db, None, self.repo.id, 5400, 600)          # every step, this repository
        e = time_limits.effective(self.db, STEP, self.repo.id)
        self.assertEqual((e["timeout_seconds"], e["timeout_from"]), (5400, "this repository"))
        self.assertEqual((e["stall_seconds"], e["stall_from"]), (600, "this repository"))

        time_limits.set_limit(self.db, STEP, self.repo.id, 10800, None)        # this step, this repository: time only
        e = time_limits.effective(self.db, STEP, self.repo.id)
        self.assertEqual((e["timeout_seconds"], e["timeout_from"]), (10800, "this step, this repository"))
        self.assertEqual((e["stall_seconds"], e["stall_from"]), (600, "this repository"))

        # Another repository sees only the step's own override.
        self.assertEqual(time_limits.effective(self.db, STEP, None)["timeout_seconds"], 7200)

    def test_clearing_an_override_lets_the_next_level_apply_and_deletes_nothing(self):
        time_limits.set_limit(self.db, STEP, self.repo.id, 10800, None)
        self.assertTrue(time_limits.clear_limit(self.db, STEP, self.repo.id))
        self.assertFalse(time_limits.clear_limit(self.db, STEP, self.repo.id))
        self.assertEqual(time_limits.effective(self.db, STEP, self.repo.id)["timeout_from"], "default (STEP_TIMEOUT_SECONDS)")
        self.assertIsNotNone(time_limits._row(self.db, STEP, self.repo.id))          # emptied, never hard-deleted

    def test_an_override_needs_a_scope_and_positive_seconds(self):
        with self.assertRaises(ValueError):
            time_limits.set_limit(self.db, None, None, 60, None)
        with self.assertRaises(ValueError):
            time_limits.set_limit(self.db, STEP, None, 0, None)


class ReporterFiles(unittest.TestCase):
    def test_progress_and_a_shareable_timing_profile_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen = []
            report = progress.Reporter(tmp, sink=seen.append)
            report.phase("parse", total=2)
            report.begin("src/A/A.csproj", "project")
            report.begin("src/B/B.csproj", "project")
            report.phase("write")
            report.finish()
            profile = json.loads((Path(tmp) / "timing-profile.json").read_text(encoding="utf-8"))
            self.assertEqual([p["phase"] for p in profile["phases"]], ["parse", "write"])
            self.assertEqual(profile["phases"][0]["items"], 2)
            self.assertEqual({r["path"] for r in profile["slowest"]["project"]}, {"src/A/A.csproj", "src/B/B.csproj"})
            self.assertEqual(set(profile["slowest"]["project"][0]), {"path", "seconds"})     # paths and durations only
            self.assertEqual(json.loads((Path(tmp) / "progress.json").read_text(encoding="utf-8"))["phase"], "completed")
            self.assertIn("parse", {p["phase"] for p in seen})


def _context(tmp: str, limits: dict) -> StepContext:
    return StepContext(step_name="throwaway-test-step", step_version="1.0.0", job_name="test-job",
                       job_execution_id=str(uuid.uuid4()), step_execution_id=str(uuid.uuid4()),
                       working_dir=tmp, output_dir=tmp, step_context={"time_limits": limits})


def stalls(context: StepContext) -> StepResult:
    """Reports one position, then keeps checking in without ever moving on."""
    report = progress.Reporter(context.output_dir, None, context.step_execution_id)
    try:
        report.phase("load", total=3)
        report.begin("a/b.csproj", "project")
        while True:
            time.sleep(0.2)
            report.check()
    finally:
        report.finish("ended")


def runs_long(context: StepContext) -> StepResult:
    """Keeps moving on, past its time limit."""
    report = progress.Reporter(context.output_dir, None, context.step_execution_id)
    try:
        report.phase("detect")
        n = 0
        while True:
            n += 1
            report.begin(f"p{n}.csproj", "project")
            time.sleep(0.1)
    finally:
        report.finish("ended")


class InProcessStepLimits(unittest.TestCase):
    def test_a_stalled_in_process_step_is_stopped_with_where_it_was(self):
        with tempfile.TemporaryDirectory() as tmp:
            started = time.monotonic()
            result = PythonAdapter({"entrypoint": "tests.test_time_limits:stalls"}).run(
                _context(tmp, {"timeout_seconds": 600, "stall_seconds": 3}))
            self.assertEqual(result.exit_status, "STALLED")
            self.assertLess(time.monotonic() - started, 30)
            self.assertIn("a/b.csproj", result.exit_message)

    def test_an_in_process_step_over_its_time_limit_is_stopped_although_it_moves(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = PythonAdapter({"entrypoint": "tests.test_time_limits:runs_long"}).run(
                _context(tmp, {"timeout_seconds": 3, "stall_seconds": 600}))
            self.assertEqual(result.exit_status, "TIMED_OUT")
            self.assertIn("time limit of 3 s", result.exit_message)

    def test_no_thread_is_left_running(self):
        before = threading.active_count()
        with tempfile.TemporaryDirectory() as tmp:
            PythonAdapter({"entrypoint": "tests.test_time_limits:stalls"}).run(_context(tmp, {"timeout_seconds": 2}))
        time.sleep(0.5)
        self.assertLessEqual(threading.active_count(), before + 1)       # at most a finishing heartbeat


if __name__ == "__main__":
    unittest.main()
