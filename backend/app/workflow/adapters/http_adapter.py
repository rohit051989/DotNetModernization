"""http adapter — remote step service, sync or polling. See
11-STEP-CONTRACT.md.

Synchronous by default: POST StepContext, receive StepResult. When
`poll.enabled` is set, a 202 response is expected to carry a correlation id,
and the engine polls a status URL until the response is terminal.

Blocking (time.sleep) is deliberate — this platform runs on a single machine
for a single operator (see 15-REPOSITORY-INGEST-UI.md); there is no worker
pool this would starve.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

from pydantic import ValidationError

from app.workflow.adapters.base import StepAdapter
from app.workflow.contract import StepContext, StepResult

_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def resolve_env_vars(value: Any) -> Any:
    """Recursively resolves `${VAR}` tokens from the engine's own environment
    at invocation time. Never store secrets in job definitions — this is how
    they're kept out."""
    if isinstance(value, str):
        return _VAR_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_env_vars(v) for v in value]
    return value


class HttpAdapter(StepAdapter):
    def __init__(self, adapter_config: dict):
        config = resolve_env_vars(adapter_config)
        if not config.get("url"):
            raise ValueError("http adapter_config.url is required")
        self._url = config["url"]
        self._method = config.get("method", "POST")
        self._timeout_seconds = config.get("timeout_seconds")
        self._headers = config.get("headers") or {}
        self._poll = config.get("poll") or {}

    def _request(
        self, url: str, method: str, body: bytes | None, timeout: float | None
    ) -> tuple[int, dict]:
        headers = {**self._headers, "Content-Type": "application/json"}
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
        payload = json.loads(raw) if raw else {}
        return status, payload

    def _invoke(self, context: StepContext) -> StepResult:
        body = context.model_dump_json().encode("utf-8")
        try:
            status, payload = self._request(self._url, self._method, body, self._timeout_seconds)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            return StepResult(
                exit_status="FAILED", exit_message=f"HTTP request to {self._url} failed: {exc}"
            )

        if self._poll.get("enabled") and status == 202:
            return self._poll_until_terminal(payload)

        return self._as_step_result(status, payload)

    def _poll_until_terminal(self, initial_payload: dict) -> StepResult:
        correlation_field = self._poll.get("correlation_field", "correlation_id")
        correlation_id = initial_payload.get(correlation_field)
        if not correlation_id:
            return StepResult(
                exit_status="FAILED",
                exit_message=(
                    f"HTTP adapter expected '{correlation_field}' in the 202 response, "
                    f"got {initial_payload!r}"
                ),
            )

        status_url = self._poll["status_url"].format(correlation_id=correlation_id)
        interval_seconds = self._poll.get("interval_seconds", 10)
        max_wait_seconds = self._poll.get("max_wait_seconds", self._timeout_seconds or 3600)

        elapsed = 0
        while elapsed <= max_wait_seconds:
            try:
                status, payload = self._request(status_url, "GET", None, self._timeout_seconds)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                return StepResult(
                    exit_status="FAILED", exit_message=f"Polling {status_url} failed: {exc}"
                )

            if status != 202:
                return self._as_step_result(status, payload)

            time.sleep(interval_seconds)
            elapsed += interval_seconds

        return StepResult(
            exit_status="FAILED",
            exit_message=f"Polling {status_url} did not complete within {max_wait_seconds}s",
        )

    @staticmethod
    def _as_step_result(status: int, payload: dict) -> StepResult:
        if status != 200:
            return StepResult(
                exit_status="FAILED", exit_message=f"HTTP step service returned {status}: {payload}"
            )
        try:
            return StepResult.model_validate(payload)
        except ValidationError as exc:
            return StepResult(
                exit_status="FAILED",
                exit_message=f"Could not parse StepResult from HTTP response: {exc}",
            )
