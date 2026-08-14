"""Unit tests for the process adapter — see 11-STEP-CONTRACT.md's 'process'
adapter section. Uses stdlib unittest: no test framework is listed in
requirements.txt, and this repo's CLAUDE.md asks not to add one without
asking first.

Run with:
    python -m unittest discover -s tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

from app.workflow.adapters.process_adapter import ProcessAdapter
from app.workflow.contract import StepContext

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _make_context(tmp_dir: str) -> StepContext:
    return StepContext(
        step_name="throwaway-test-step",
        step_version="1.0.0",
        job_name="test-job",
        job_execution_id="11111111-1111-1111-1111-111111111111",
        step_execution_id="22222222-2222-2222-2222-222222222222",
        working_dir=tmp_dir,
        output_dir=tmp_dir,
    )


class ProcessAdapterHappyPathTests(unittest.TestCase):
    def test_echo_step_completes(self):
        adapter = ProcessAdapter(
            {"command": [sys.executable, str(FIXTURES_DIR / "echo_step.py")]}
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = adapter.run(_make_context(tmp_dir))

        self.assertEqual(result.exit_status, "COMPLETED")
        self.assertIn("throwaway-test-step", result.exit_message)


class ProcessAdapterNonZeroExitTests(unittest.TestCase):
    def test_non_zero_exit_fails_with_stderr_captured(self):
        adapter = ProcessAdapter(
            {"command": [sys.executable, str(FIXTURES_DIR / "fail_step.py")]}
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = adapter.run(_make_context(tmp_dir))

        self.assertEqual(result.exit_status, "FAILED")
        self.assertIn("1", result.exit_message)
        self.assertTrue(result.diagnostics)
        self.assertIn("boom", result.diagnostics[0].message)


class ProcessAdapterUnparseableStdoutTests(unittest.TestCase):
    def test_exit_zero_with_unparseable_stdout_fails(self):
        adapter = ProcessAdapter(
            {"command": [sys.executable, str(FIXTURES_DIR / "garbage_step.py")]}
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = adapter.run(_make_context(tmp_dir))

        self.assertEqual(result.exit_status, "FAILED")
        self.assertIn("parse", result.exit_message.lower())


class ProcessAdapterTimeoutTests(unittest.TestCase):
    def test_slow_step_times_out(self):
        adapter = ProcessAdapter(
            {
                "command": [sys.executable, str(FIXTURES_DIR / "slow_step.py")],
                "timeout_seconds": 1,
            }
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = adapter.run(_make_context(tmp_dir))

        self.assertEqual(result.exit_status, "FAILED")
        self.assertIn("timed out", result.exit_message.lower())


class ProcessAdapterChecksumVerificationTests(unittest.TestCase):
    """Exercises the BASE adapter's checksum verification (see
    app/workflow/adapters/base.py) through the process adapter, since the
    process adapter has no verification logic of its own."""

    def test_correct_checksum_passes_through(self):
        adapter = ProcessAdapter(
            {"command": [sys.executable, str(FIXTURES_DIR / "checksum_step.py")]}
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = adapter.run(_make_context(tmp_dir))

        self.assertEqual(result.exit_status, "COMPLETED")
        self.assertEqual(len(result.outputs), 1)

    def test_mismatched_checksum_fails(self):
        adapter = ProcessAdapter(
            {
                "command": [sys.executable, str(FIXTURES_DIR / "checksum_step.py")],
                "env": {"CHECKSUM_MODE": "wrong"},
            }
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = adapter.run(_make_context(tmp_dir))

        self.assertEqual(result.exit_status, "FAILED")
        self.assertIn("Checksum verification failed", result.exit_message)
        self.assertEqual(result.outputs, [])


if __name__ == "__main__":
    unittest.main()
