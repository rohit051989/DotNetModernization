"""Adapter base — see 11-STEP-CONTRACT.md 'Adapters'.

Every adapter takes a StepContext and returns a StepResult over the same
envelope, regardless of transport. Checksum verification on declared outputs
happens HERE, once, after the concrete adapter's `_invoke` returns — so no
adapter subclass has to reimplement it. So does the version check: the version
a step reports for an artifact must be the version the artifact declares in
itself (release 7; dependency-assessment once wrote 1.6.0 and reported 1.5.0).
"""

import hashlib
import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.workflow.contract import Diagnostic, StepContext, StepResult

_WINDOWS_DRIVE_RE = re.compile(r"^/[A-Za-z]:")


def local_path_from_uri(uri: str) -> Path:
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
    digest = hashlib.sha256(local_path_from_uri(uri).read_bytes()).hexdigest()
    return f"sha256:{digest}"


def declared_version(uri: str) -> str | None:
    """The version a JSON artifact declares in itself: its top-level `artifactVersion` or `artifact_version`, or a
    SARIF log's `version`. None for a file that is not a JSON object or declares none."""
    path = local_path_from_uri(uri)
    if path.suffix.lower() not in (".json", ".sarif"):
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    for key in ("artifactVersion", "artifact_version"):
        if isinstance(document.get(key), str):
            return document[key]
    if "runs" in document and isinstance(document.get("version"), str):
        return document["version"]
    return None


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

        versions = []
        for output in result.outputs:
            written = declared_version(output.uri)
            if written is not None and written != output.artifact_version:
                versions.append(f"{output.artifact_type} ({output.uri}): reported {output.artifact_version}, the file declares {written}")

        if not mismatches and not versions:
            return result

        message = "; ".join(filter(None, [
            "Checksum verification failed: " + "; ".join(mismatches) if mismatches else "",
            "Artifact version mismatch: " + "; ".join(versions) if versions else "",
        ]))
        return result.model_copy(
            update={
                "exit_status": "FAILED",
                "exit_message": message,
                "outputs": [],
                "diagnostics": [
                    *result.diagnostics,
                    *(Diagnostic(level="error", code="CHECKSUM_MISMATCH", message=m) for m in mismatches),
                    *(Diagnostic(level="error", code="ARTIFACT_VERSION_MISMATCH", message=m) for m in versions),
                ],
            }
        )
