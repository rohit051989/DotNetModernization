"""python adapter — in-process import and call. See 11-STEP-CONTRACT.md.

For our own steps. Fastest, no serialisation overhead, shares the DB session
pool (the engine passes `database_url` in StepContext for steps that want it).
"""

import importlib
import traceback

from app.workflow.adapters.base import StepAdapter
from app.workflow.contract import Diagnostic, StepContext, StepResult


class PythonAdapter(StepAdapter):
    def __init__(self, adapter_config: dict):
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

    def _invoke(self, context: StepContext) -> StepResult:
        # Steps run in-process here, so a bug in one is a Python exception, not
        # a subprocess exit code — caught and turned into FAILED so the
        # adapter contract (always returns a StepResult) holds uniformly
        # across adapter types.
        try:
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
