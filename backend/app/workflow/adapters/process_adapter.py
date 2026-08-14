"""process adapter — local executable via stdin/stdout JSON. See
11-STEP-CONTRACT.md.

For steps written by anyone, in any language. The subprocess's only
obligation: read JSON from stdin, write a single JSON object to stdout, exit
0. Anything else it wants to log goes to stderr.
"""

import json
import os
import subprocess

from pydantic import ValidationError

from app.workflow.adapters.base import StepAdapter
from app.workflow.contract import Diagnostic, StepContext, StepResult

_TAIL_CHARS = 8192  # matches wf_step_executions.stderr_tail's "last 8KB" convention


def _tail(text: str) -> str:
    return text[-_TAIL_CHARS:] if text else text


class ProcessAdapter(StepAdapter):
    def __init__(self, adapter_config: dict):
        command = adapter_config.get("command")
        if not command or not isinstance(command, list):
            raise ValueError("process adapter_config.command must be a non-empty list")
        self._command = command
        self._cwd = adapter_config.get("cwd")
        self._timeout_seconds = adapter_config.get("timeout_seconds")
        self._extra_env = adapter_config.get("env")

    def _invoke(self, context: StepContext) -> StepResult:
        env = None
        if self._extra_env:
            env = {**os.environ, **{k: str(v) for k, v in self._extra_env.items()}}

        try:
            completed = subprocess.run(
                self._command,
                input=context.model_dump_json(),
                capture_output=True,
                text=True,
                cwd=self._cwd,
                env=env,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return StepResult(
                exit_status="FAILED",
                exit_message=(
                    f"Step timed out after {self._timeout_seconds}s: "
                    f"{' '.join(self._command)}"
                ),
                diagnostics=self._stderr_diagnostic(exc.stderr),
            )
        except OSError as exc:
            # The command itself could not be started (bad path, no permission, ...).
            return StepResult(
                exit_status="FAILED",
                exit_message=f"Could not start '{' '.join(self._command)}': {exc}",
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
