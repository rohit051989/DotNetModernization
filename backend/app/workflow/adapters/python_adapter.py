"""python adapter — in-process import and call. See 11-STEP-CONTRACT.md.

For our own steps. Fastest, no serialisation overhead, shares the DB session
pool (the engine passes `database_url` in StepContext for steps that want it).

A step whose entrypoint declares a `session` parameter is additionally given
**the engine's own session**, so its writes are committed together with the
step's own completion: the engine commits at each step boundary (see
app/workflow/runtime/executor.py), and a step's writes land in the same
commit as its COMPLETED row and artifacts. Such a step must not commit
itself — a half-finished step's writes would then outlive a crash that
leaves the step to be rerun.

Steps that open their own session (`repository_ingest`) keep working
unchanged; with per-step commits they can also see the execution's rows.
"""

import importlib
import inspect
import json
import threading
import time
import traceback
from pathlib import Path

from app.config import settings
from app.workflow import processes, progress
from app.workflow.adapters.base import StepAdapter
from app.workflow.contract import Diagnostic, StepContext, StepResult


class PythonAdapter(StepAdapter):
    def __init__(self, adapter_config: dict, session=None):
        entrypoint = adapter_config.get("entrypoint")
        if not entrypoint or ":" not in entrypoint:
            raise ValueError(
                "python adapter_config.entrypoint must be 'module.path:function', "
                f"got {entrypoint!r}"
            )
        self._entrypoint = entrypoint
        module_name, func_name = entrypoint.split(":", 1)
        module = importlib.import_module(module_name)
        func = getattr(module, func_name, None)
        if not callable(func):
            raise ValueError(f"'{entrypoint}' does not resolve to a callable")
        self._func = func
        self._session = session
        self._wants_session = "session" in inspect.signature(func).parameters

    def _invoke(self, context: StepContext) -> StepResult:
        """Runs the step on a worker thread while this thread watches its time and stall limits (rbc-release-5). A step
        over a limit is asked to stop: it stops at its next progress checkpoint (Reporter.check), and any child process
        it is waiting on is ended with its whole tree (app.workflow.processes). It is then reported TIMED_OUT or
        STALLED with where it was. The engine waits for it to stop rather than abandon a thread that may hold the
        engine's own session."""
        limits = (context.step_context or {}).get("time_limits") or {}
        timeout = limits.get("timeout_seconds") or settings.step_timeout_seconds
        stall = limits.get("stall_seconds") or settings.step_stall_seconds
        step_id = context.step_execution_id
        box: dict = {}
        job_id = progress.current_job()

        def work():
            progress.running(step_id, job_id)
            try:
                box["result"] = self._call(context)
            finally:
                progress.running(None, None)

        worker = threading.Thread(target=work, name=f"step-{context.step_name}", daemon=True)
        started = time.monotonic()
        worker.start()
        stopped = None
        while worker.is_alive():
            worker.join(1)
            if stopped:
                continue
            now = time.monotonic()
            moved = progress.moved_at(step_id)
            if now - started > timeout:
                stopped = ("TIMED_OUT", f"time limit of {int(timeout)} s reached")
            elif moved is not None and now - moved > stall:
                stopped = ("STALLED", f"no progress for {int(now - moved)} s (stall limit {int(stall)} s)")
            elif job_id and job_id in progress._cancelled_jobs:
                stopped = ("STOPPED", "the job was stopped by an operator")
            if stopped:
                progress.request_stop(step_id, stopped[1])
        progress.clear_stop(step_id)
        last = progress.last_position(step_id)
        progress.forget(step_id)
        if stopped:
            where = processes.describe_position(last)
            _record_stop(context, stopped[0], stopped[1], time.monotonic() - started, last)
            return StepResult(exit_status=stopped[0],
                              exit_message=f"Step {({'TIMED_OUT': 'timed out', 'STALLED': 'stalled'}).get(stopped[0], 'stopped')}: {stopped[1]}; "
                                           f"where it was: {where}. It stopped at its next checkpoint, and any process it "
                                           "ran was ended with its whole tree. Where it was and its timing profile are in "
                                           "stopped.json and timing-profile.json.")
        return box["result"]

    def _call(self, context: StepContext) -> StepResult:
        # Steps run in-process here, so a bug in one is a Python exception, not
        # a subprocess exit code — caught and turned into FAILED so the
        # adapter contract (always returns a StepResult) holds uniformly
        # across adapter types.
        try:
            if self._wants_session:
                result = self._func(context, session=self._session)
            else:
                result = self._func(context)
            if not isinstance(result, StepResult):
                raise TypeError(
                    f"'{self._entrypoint}' must return a StepResult, got {type(result)!r}"
                )
            return result
        except Exception as exc:
            return StepResult(
                exit_status="FAILED",
                exit_message=f"{type(exc).__name__}: {exc}",
                diagnostics=[
                    Diagnostic(
                        level="error",
                        code="PYTHON_ADAPTER_EXCEPTION",
                        message=traceback.format_exc(),
                    )
                ],
            )


def _record_stop(context: StepContext, status: str, why: str, seconds: float, last: dict | None) -> None:
    """stopped.json in the step's output folder, as the process adapter writes it: why, and where the step was."""
    try:
        out = Path(context.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "stopped.json").write_text(json.dumps({"status": status, "why": why, "seconds": round(seconds, 1),
                                                      "lastProgress": last}, indent=1), encoding="utf-8")
    except OSError:
        pass
