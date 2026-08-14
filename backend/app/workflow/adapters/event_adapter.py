"""event adapter — message-based, not yet implemented. See
11-STEP-CONTRACT.md.

Registered as a known adapter type now so job definitions can reference it
before the transport exists, but it needs a broker we do not have yet.
Construction succeeds (so registration works); invoking it raises.
"""

from app.workflow.adapters.base import StepAdapter
from app.workflow.contract import StepContext, StepResult


class EventAdapter(StepAdapter):
    def __init__(self, adapter_config: dict):
        self._publish_to = adapter_config.get("publish_to")
        self._reply_to = adapter_config.get("reply_to")
        self._correlation_field = adapter_config.get("correlation_field")
        self._timeout_seconds = adapter_config.get("timeout_seconds")

    def _invoke(self, context: StepContext) -> StepResult:
        raise NotImplementedError(
            "event adapter has no message broker configured yet — see "
            "11-STEP-CONTRACT.md 'event — message-based'"
        )
