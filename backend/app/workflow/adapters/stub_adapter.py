"""stub adapter — not yet built. See 11-STEP-CONTRACT.md.

Every one of the 51 lifecycle steps registers with this adapter at the
outset, so the pipeline is runnable end to end before most steps exist.
"""

from app.workflow.adapters.base import StepAdapter
from app.workflow.contract import StepContext, StepResult


class StubAdapter(StepAdapter):
    def __init__(self, adapter_config: dict):
        self._exit_status = adapter_config.get("exit_status", "NOT_IMPLEMENTED")
        self._message = adapter_config.get("message")

    def _invoke(self, context: StepContext) -> StepResult:
        return StepResult(exit_status=self._exit_status, exit_message=self._message)
