"""app.workflow.processes: no child process can make its caller wait forever (release 5)."""
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from app.workflow import processes

BACKEND = Path(__file__).resolve().parents[1]


def child(mode: str) -> list[str]:
    return [sys.executable, "-m", "app.workflow.processes", mode]


def alive(pid: int) -> bool:
    from app.heartbeat import pid_alive
    return pid_alive(pid)


class ProcessRunner(unittest.TestCase):
    def test_a_child_flooding_stderr_never_blocks(self):
        outcome = processes.run(child("flood"), cwd=BACKEND, timeout=60)
        self.assertEqual((outcome.returncode, outcome.stdout.strip()), (0, "done"))
        self.assertGreater(len(outcome.stderr), 4_000_000)

    def test_a_stalled_child_is_stopped_with_its_last_position(self):
        started = time.monotonic()
        outcome = processes.run(child("stall"), cwd=BACKEND, timeout=600, stall_seconds=5)
        self.assertTrue(outcome.stalled)
        self.assertLess(time.monotonic() - started, 30)          # not the 600 s time limit
        self.assertEqual(outcome.last_progress["item"], "a/b.csproj")
        self.assertIn("phase load, 3 of 9, at a/b.csproj", processes.describe_position(outcome.last_progress))
        self.assertGreater(outcome.progress_lines, 1)              # it kept reporting; it just never moved

    def test_a_time_limit_ends_the_whole_tree_and_never_waits_on_a_grandchilds_pipe(self):
        started = time.monotonic()
        outcome = processes.run(child("spawn"), cwd=BACKEND, timeout=5)
        self.assertTrue(outcome.timed_out)
        self.assertLess(time.monotonic() - started, 40)
        # Every python process started for this test is gone: the child and the grandchild holding its pipes.
        time.sleep(1)
        leftover = subprocess.run(["powershell", "-NoProfile", "-Command",
                                   "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ForEach-Object CommandLine"],
                                  capture_output=True, text=True).stdout
        self.assertNotIn("time.sleep(600)", leftover)

    def test_a_child_that_exits_by_itself_leaves_nothing_running(self):
        started = time.monotonic()
        outcome = processes.run(child("leave"), cwd=BACKEND, timeout=60)
        self.assertEqual((outcome.returncode, outcome.stdout.strip()), (0, "left"))
        self.assertLess(time.monotonic() - started, 10)
        time.sleep(1)
        leftover = subprocess.run(["powershell", "-NoProfile", "-Command",
                                   "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ForEach-Object CommandLine"],
                                  capture_output=True, text=True).stdout
        self.assertNotIn("time.sleep(601)", leftover)

    def test_an_operator_stop_ends_the_child_at_once(self):
        from app.workflow import progress
        job, box = "job-" + str(time.monotonic()), {}

        def step():
            progress.running("step-under-test", job)
            try:
                box["outcome"] = processes.run(child("spawn"), cwd=BACKEND, timeout=600)
            finally:
                progress.running(None, None)

        worker = threading.Thread(target=step)
        worker.start()
        time.sleep(2)
        started = time.monotonic()
        progress.cancel_job(job)
        worker.join(60)
        self.assertFalse(worker.is_alive())
        self.assertLess(time.monotonic() - started, 30)
        self.assertIn("stopped by an operator", box["outcome"].stopped_why)

    def test_progress_lines_are_parsed_and_other_lines_kept(self):
        self.assertEqual(processes.parse_progress('##progress {"phase": "parse", "done": 1}'), {"phase": "parse", "done": 1})
        self.assertIsNone(processes.parse_progress("an ordinary line"))
        self.assertIsNone(processes.parse_progress("##progress not json"))


if __name__ == "__main__":
    unittest.main()
