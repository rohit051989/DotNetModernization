"""Progress and timing for a step (rbc-release-5).

Every discovery step reports progress at least every 15 seconds — its phase, and items done out of the total — and
writes a timing profile a person can share without exposing client code: time per phase, and the slowest projects
and files by path and duration only.

    report = Reporter(output_dir, sink=...)
    report.phase("parse", total=len(projects))
    for project in projects:
        with report.item(project.path, kind="project"):
            ...
    report.finish()

Where progress goes (`sink`):
- a step run as its own process prints ``##progress {json}`` lines on stderr (`stderr_sink`), which the process
  runner reads (app/workflow/processes.py);
- a step run inside the backend (the python adapter) writes it to its step execution row (`database_sink`), and is
  stopped cooperatively: `check()`, called at every item, raises StepStopped once the engine asked it to stop (a time
  or stall limit); any child process it runs is ended with its tree by the process runner.

Files, rewritten at every heartbeat and at the end, so a step stopped part-way leaves them behind:
- ``progress.json``: the last position;
- ``timing-profile.json``: phases, the slowest projects and files, and where the step was.
"""
import json
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

HEARTBEAT_SECONDS = 10
EMIT_SECONDS = 2
SLOWEST = 25
_stop_requests: dict[str, str] = {}      # step execution id -> why the engine asked it to stop
_moved: dict[str, tuple[tuple, float]] = {}   # step execution id -> (position, when it last changed)
_last: dict[str, dict] = {}                   # step execution id -> the last progress it reported
_current = threading.local()                  # the in-process step this thread is running


_cancelled_jobs: set[str] = set()            # job executions an operator stopped (POST .../stop)


def running(step_execution_id: str | None, job_execution_id: str | None = None) -> None:
    """Marks this thread as running `step_execution_id` of `job_execution_id` (the executor's thread, and the python
    adapter's worker thread)."""
    _current.step = step_execution_id
    _current.job = job_execution_id


def current_job() -> str | None:
    return getattr(_current, "job", None)


def cancel_job(job_execution_id: str) -> None:
    """An operator stopped this job: its running step stops, and the process tree it is waiting on ends at once."""
    _cancelled_jobs.add(str(job_execution_id))


def stop_requested() -> str | None:
    """Why the step this thread runs must stop — the engine's time or stall limit, or an operator's stop — or None.
    Read by the process runner, which then ends the child process tree it is waiting on, and by Reporter.check."""
    step, job = getattr(_current, "step", None), getattr(_current, "job", None)
    if step and step in _stop_requests:
        return _stop_requests[step]
    if job and job in _cancelled_jobs:
        return "the job was stopped by an operator"
    return None


def last_position(step_execution_id: str) -> dict | None:
    """The last progress an in-process step reported: phase, done, total, item."""
    return _last.get(step_execution_id)


def forget(step_execution_id: str) -> None:
    """Once the engine has the step's result: nothing kept about it in memory."""
    _moved.pop(step_execution_id, None)
    _last.pop(step_execution_id, None)


def moved_at(step_execution_id: str) -> float | None:
    """When the step's reported position last changed (time.monotonic), or None if it never reported."""
    entry = _moved.get(step_execution_id)
    return entry[1] if entry else None


class StepStopped(Exception):
    """Raised inside an in-process step the engine asked to stop (a time or stall limit)."""


def request_stop(step_execution_id: str, why: str) -> None:
    _stop_requests[step_execution_id] = why


def clear_stop(step_execution_id: str) -> None:
    _stop_requests.pop(step_execution_id, None)


def stderr_sink(progress: dict) -> None:
    sys.stderr.write("##progress " + json.dumps(progress, ensure_ascii=False) + "\n")
    sys.stderr.flush()


def database_sink(step_execution_id: str) -> Callable[[dict], None]:
    """Writes progress to the step execution row, in its own short transaction (never the engine's)."""
    def write(progress: dict) -> None:
        from sqlalchemy import text
        from app.db import SessionLocal
        with SessionLocal() as db:
            db.execute(text("UPDATE wf_step_executions SET progress = CAST(:p AS jsonb), progress_at = now() WHERE id = :i"),
                       {"p": json.dumps(progress), "i": step_execution_id})
            db.commit()
    return write


def for_step(context) -> "Reporter":
    """The reporter for an in-process step (the python adapter): its output folder, and its step execution row."""
    step_id = getattr(context, "step_execution_id", None)
    return Reporter(getattr(context, "output_dir", None), database_sink(str(step_id)) if step_id else None,
                    str(step_id) if step_id else None)


class Reporter:
    def __init__(self, output_dir: str | Path | None, sink: Callable[[dict], None] | None = None,
                 step_execution_id: str | None = None):
        self.output_dir = Path(output_dir) if output_dir else None
        self.sink = sink
        self.step_execution_id = step_execution_id
        self.started = time.monotonic()
        self.position = {"phase": "starting", "done": 0, "total": None, "item": None}
        self.phases: list[dict] = []
        self.timings: dict[str, list[dict]] = {}
        self._phase_started = self.started
        self._lock = threading.Lock()
        self._emitted = 0.0
        self._open = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._thread.start()
        self._emit()

    # ---- what the step calls
    def phase(self, name: str, total: int | None = None) -> None:
        self.end()
        with self._lock:
            self._close_phase()
            self.position = {"phase": name, "done": 0, "total": total, "item": None}
        self._emit()

    @contextmanager
    def item(self, name: str, kind: str = "item"):
        self.check()
        with self._lock:
            self.position = {**self.position, "item": name}
        self._emit(force=False)
        started = time.monotonic()
        try:
            yield
        finally:
            seconds = time.monotonic() - started
            with self._lock:
                self.timings.setdefault(kind, []).append({"path": name, "seconds": round(seconds, 3)})
                self.position = {**self.position, "done": (self.position.get("done") or 0) + 1}
            self._emit(force=False)

    def begin(self, name: str, kind: str = "item") -> None:
        """The next item of a loop, without a with-block: ends the item begun before (if any) and starts this one."""
        self.end()
        self.check()
        with self._lock:
            self.position = {**self.position, "item": name}
            self._open = (name, kind, time.monotonic())
        self._emit(force=False)

    def end(self) -> None:
        """Ends the item begun last; phase() and finish() do it too."""
        with self._lock:
            if self._open is None:
                return
            name, kind, started = self._open
            self._open = None
            self.timings.setdefault(kind, []).append({"path": name, "seconds": round(time.monotonic() - started, 3)})
            self.position = {**self.position, "done": (self.position.get("done") or 0) + 1}
        self._emit(force=False)

    def check(self) -> None:
        """Raises StepStopped when the engine or an operator asked this in-process step to stop."""
        if self.step_execution_id and self.step_execution_id in _stop_requests:
            raise StepStopped(_stop_requests[self.step_execution_id])
        if (why := stop_requested()) is not None:
            raise StepStopped(why)

    def finish(self, outcome: str = "completed") -> None:
        self.end()
        with self._lock:
            self._close_phase()
            self.position = {**self.position, "phase": outcome, "item": None}
        self._stop.set()
        self._emit()

    # ---- inside
    def _close_phase(self) -> None:
        now = time.monotonic()
        if self.position.get("phase") not in (None, "starting"):
            self.phases.append({"phase": self.position["phase"], "seconds": round(now - self._phase_started, 3),
                                "items": self.position.get("done") or 0})
        self._phase_started = now

    def _heartbeat(self) -> None:
        while not self._stop.wait(HEARTBEAT_SECONDS):
            self._emit()

    def snapshot(self) -> dict:
        with self._lock:
            return {**self.position, "elapsedSeconds": round(time.monotonic() - self.started, 1),
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def profile(self) -> dict:
        with self._lock:
            current = None
            if self.position.get("phase") not in (None, "completed"):
                current = {"phase": self.position.get("phase"), "seconds": round(time.monotonic() - self._phase_started, 3),
                           "items": self.position.get("done") or 0, "running": True}
            return {
                "format": 1,
                "note": "Durations and paths only: no code, no file content, no values.",
                "elapsedSeconds": round(time.monotonic() - self.started, 1),
                "position": {k: self.position.get(k) for k in ("phase", "done", "total", "item")},
                "phases": self.phases + ([current] if current else []),
                "slowest": {kind: sorted(rows, key=lambda r: -r["seconds"])[:SLOWEST] for kind, rows in self.timings.items()},
            }

    def _emit(self, force: bool = True) -> None:
        """Records that the step moved on, at once; and writes the files and the sink — at once for a new phase, the
        heartbeat and the end, and for items at most every EMIT_SECONDS, so a step with many small items is not
        slowed down by its own reporting."""
        progress = self.snapshot()
        if self.step_execution_id:
            position = (progress.get("phase"), progress.get("done"), progress.get("item"))
            previous = _moved.get(self.step_execution_id)
            if previous is None or previous[0] != position:
                _moved[self.step_execution_id] = (position, time.monotonic())
            if progress.get("phase") not in ("completed", "ended"):
                _last[self.step_execution_id] = progress
        now = time.monotonic()
        if not force and now - self._emitted < EMIT_SECONDS:
            return
        self._emitted = now
        if self.sink:
            try:
                self.sink(progress)
            except Exception:       # progress must never fail the step
                pass
        if self.output_dir:
            try:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                (self.output_dir / "progress.json").write_text(json.dumps(progress, indent=1), encoding="utf-8")
                (self.output_dir / "timing-profile.json").write_text(json.dumps(self.profile(), indent=1), encoding="utf-8")
            except OSError:
                pass
