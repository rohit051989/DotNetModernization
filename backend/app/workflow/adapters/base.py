"""Adapter base — see 11-STEP-CONTRACT.md 'Adapters'.

Every adapter takes a StepContext and returns a StepResult over the same
envelope, regardless of transport. Checksum verification on declared outputs
happens HERE, once, after the concrete adapter's `_invoke` returns — so no
adapter subclass has to reimplement it.
"""

import hashlib
import re
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.workflow.contract import Diagnostic, StepContext, StepResult

_WINDOWS_DRIVE_RE = re.compile(r"^/[A-Za-z]:")


def _local_path(uri: str) -> Path:
    """Resolves an artifact URI to a local filesystem path. Only `file://` and
    bare paths are supported — this platform has no object storage (see
    15-REPOSITORY-INGEST-UI.md's single-machine operating model)."""
    parsed = urlparse(uri)
    if parsed.scheme not in ("", "file"):
        raise ValueError(f"unsupported artifact URI scheme '{parsed.scheme}' in '{uri}'")

    raw = unquote(parsed.path) if parsed.scheme == "file" else uri
    if _WINDOWS_DRIVE_RE.match(raw):
        raw = raw[1:]  # file:///D:/... parses to a leading-slash path pathlib mishandles on Windows
    return Path(raw)


def compute_checksum(uri: str) -> str:
    """SHA-256 of the artifact's content, in the `sha256:<hex>` form used
    throughout the envelope."""
    digest = hashlib.sha256(_local_path(uri).read_bytes()).hexdigest()
    return f"sha256:{digest}"


class StepAdapter(ABC):
    """Base class for all adapter types. Subclasses implement `_invoke`;
    callers use `run`, never `_invoke` directly."""

    @abstractmethod
    def _invoke(self, context: StepContext) -> StepResult:
        """Adapter-specific invocation. May raise — `run` does not catch
        exceptions, so an adapter that cannot produce a StepResult at all
        (e.g. `event`, with no broker) should simply let the error propagate."""

    def run(self, context: StepContext) -> StepResult:
        result = self._invoke(context)
        return self._verify_output_checksums(result)

    def _verify_output_checksums(self, result: StepResult) -> StepResult:
        if not result.outputs:
            return result

        mismatches = []
        for output in result.outputs:
            try:
                actual = compute_checksum(output.uri)
            except (OSError, ValueError) as exc:
                mismatches.append(f"{output.artifact_type} ({output.uri}): {exc}")
                continue
            if actual != output.checksum:
                mismatches.append(
                    f"{output.artifact_type} ({output.uri}): "
                    f"declared {output.checksum}, computed {actual}"
                )

        if not mismatches:
            return result

        return result.model_copy(
            update={
                "exit_status": "FAILED",
                "exit_message": "Checksum verification failed: " + "; ".join(mismatches),
                "outputs": [],
                "diagnostics": [
                    *result.diagnostics,
                    *(
                        Diagnostic(level="error", code="CHECKSUM_MISMATCH", message=m)
                        for m in mismatches
                    ),
                ],
            }
        )
