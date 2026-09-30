"""Adapter factory — resolves a step's adapter_type/adapter_config (as stored
in wf_step_registrations) into a StepAdapter instance. See
11-STEP-CONTRACT.md 'Adapters'."""

from app.workflow.adapters.base import StepAdapter
from app.workflow.adapters.event_adapter import EventAdapter
from app.workflow.adapters.http_adapter import HttpAdapter
from app.workflow.adapters.process_adapter import ProcessAdapter
from app.workflow.adapters.python_adapter import PythonAdapter
from app.workflow.adapters.stub_adapter import StubAdapter

_ADAPTER_CLASSES: dict[str, type[StepAdapter]] = {
    "python": PythonAdapter,
    "process": ProcessAdapter,
    "http": HttpAdapter,
    "event": EventAdapter,
    "stub": StubAdapter,
}


def create_adapter(adapter_type: str, adapter_config: dict, session=None) -> StepAdapter:
    """`session` is the engine's own Session, offered only to the `python`
    adapter — the one adapter that runs inside the engine's transaction. Every
    other adapter is out-of-process or remote by definition and could not use
    it."""
    try:
        adapter_class = _ADAPTER_CLASSES[adapter_type]
    except KeyError:
        raise ValueError(f"unknown adapter_type '{adapter_type}'") from None
    if adapter_type == "python":
        return adapter_class(adapter_config, session=session)
    return adapter_class(adapter_config)


__all__ = ["StepAdapter", "create_adapter"]
