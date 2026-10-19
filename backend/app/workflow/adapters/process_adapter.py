"""process adapter — local executable via stdin/stdout JSON. See
11-STEP-CONTRACT.md.

For steps written by anyone, in any language. The subprocess's only
obligation: read JSON from stdin, write a single JSON object to stdout, exit
0. Anything else it wants to log goes to stderr.
"""

import json
import os
from pathlib import Path

from pydantic import ValidationError

from app.config import settings
from app.workflow import processes
from app.workflow.adapters.base import StepAdapter
from app.workflow.contract import Diagnostic, StepContext, StepResult

_TAIL_CHARS = 8192  # matches wf_step_executions.stderr_tail's "last 8KB" convention


def _tail(text: str) -> str:
    return text[-_TAIL_CHARS:] if text else text


def _is_path_like(token: str) -> bool:
    """A bare command name (`python`, `node`) is left for PATH search; a
    relative or absolute path (contains a separator) is resolved against
    PLATFORM_ROOT — see 11-STEP-CONTRACT.md's "process" adapter section."""
    return "/" in token or "\\" in token


def _resolve(token: str, platform_root: Path) -> str:
    candidate = Path(token)
    return str(candidate if candidate.is_absolute() else platform_root / candidate)


class ProcessAdapter(StepAdapter):
    def __init__(self, adapter_config: dict):
        command = adapter_config.get("command")
        if not command or not isinstance(command, list):
            raise ValueError("process adapter_config.command must be a non-empty list")

        platform_root = Path(settings.platform_root)
        self._platform_root = platform_root

        executable = command[0]
        resolved_executable = _resolve(executable, platform_root) if _is_path_like(executable) else executable
        self._command = [resolved_executable, *command[1:]]

        raw_cwd = adapter_config.get("cwd")
        # No cwd declared: default to PLATFORM_ROOT rather than inheriting
        # whatever directory the backend process happens to have been
        # launched from (e.g. `backend/`, per 01-ENVIRONMENT-SETUP.md's run
        # commands) — the mismatch this class used to have.
        self._cwd = _resolve(raw_cwd, platform_root) if raw_cwd else str(platform_root)

        self._extra_env = adapter_config.get("env")
        # Where progress goes while the step runs (the executor sets it: the step execution row).
        self.progress_sink = None

    def _invoke(self, context: StepContext) -> StepResult:
        env = None
        if self._extra_env:
            env = {**os.environ, **{k: str(v) for k, v in self._extra_env.items()}}

        executable = self._command[0]
        if _is_path_like(executable) and not Path(executable).exists():
            return StepResult(
                exit_status="FAILED",
                exit_message=(
                    f"Step executable not found: '{executable}' "
                    f"(resolved against PLATFORM_ROOT='{self._platform_root}')"
                ),
            )

        # The time and stall limits in effect for this step on this repository (app.workflow.time_limits), set by
        # the executor; the defaults when a caller gives none.
        limits = (context.step_context or {}).get("time_limits") or {}
        timeout = limits.get("timeout_seconds") or settings.step_timeout_seconds
        stall = limits.get("stall_seconds") or settings.step_stall_seconds
        try:
            completed = processes.run(self._command, cwd=self._cwd, env=env, input_text=context.model_dump_json(),
                                      timeout=timeout, stall_seconds=stall, on_progress=self.progress_sink)
        except OSError as exc:
            # The command itself could not be started (bad path, no permission, ...).
            return StepResult(
                exit_status="FAILED",
                exit_message=f"Could not start '{' '.join(self._command)}': {exc}",
            )

        if completed.timed_out or completed.stalled:
            where = processes.describe_position(completed.last_progress)
            status = "TIMED_OUT" if completed.timed_out else "STALLED"
            if (completed.stopped_why or "").startswith("the step was stopped: the job was stopped"):
                status = "STOPPED"
            _record_stop(context, status, completed)
            return StepResult(
                exit_status=status,
                exit_message=(f"Step {({'TIMED_OUT': 'timed out', 'STALLED': 'stalled'}).get(status, 'stopped')}: {completed.stopped_why}; "
                              f"where it was: {where}. Its whole process tree was ended. Where it was and its timing "
                              f"profile are in {Path(context.output_dir).name}/stopped.json and timing-profile.json; "
                              "a rerun continues from the last completed project."),
                diagnostics=self._stderr_diagnostic(completed.stderr),
            )

        if completed.returncode != 0:
            return StepResult(
                exit_status="FAILED",
                exit_message=f"Process exited {completed.returncode}: {' '.join(self._command)}",
                diagnostics=self._stderr_diagnostic(completed.stderr),
            )

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return StepResult(
                exit_status="FAILED",
                exit_message=f"Could not parse StepResult JSON from stdout: {exc}",
                diagnostics=self._stderr_diagnostic(completed.stderr),
            )

        try:
            return StepResult.model_validate(payload)
        except ValidationError as exc:
            return StepResult(
                exit_status="FAILED",
                exit_message=f"stdout did not contain a valid StepResult: {exc}",
                diagnostics=self._stderr_diagnostic(completed.stderr),
            )

    @staticmethod
    def _stderr_diagnostic(stderr: str | None) -> list[Diagnostic]:
        tail = _tail(stderr)
        if not tail:
            return []
        return [Diagnostic(level="error", code="PROCESS_STDERR", message=tail)]


def _record_stop(context: StepContext, status: str, outcome: "processes.Outcome") -> None:
    """stopped.json in the step's output folder: why it was stopped and where it was — the last progress it reported.
    Its own timing-profile.json, which the step rewrites as it runs, stays beside it."""
    try:
        out = Path(context.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "stopped.json").write_text(json.dumps({
            "status": status, "why": outcome.stopped_why, "seconds": round(outcome.seconds, 1),
            "lastProgress": outcome.last_progress, "progressLines": outcome.progress_lines,
        }, indent=1), encoding="utf-8")
    except OSError:
        pass
