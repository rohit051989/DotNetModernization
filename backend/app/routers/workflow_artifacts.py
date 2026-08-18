"""Artifact access — see 20-WORKFLOW-OBSERVABILITY-UI.md Part A.

`content` and `download` both re-verify the on-disk checksum against
`wf_artifacts.checksum` before serving anything — an artifact that has
drifted from its recorded checksum is a real finding, never served silently.
"""

import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.errors import ErrorResponse, error
from app.workflow.adapters.base import local_path_from_uri
from app.workflow.runtime import artifacts as artifacts_service
from app.workflow.runtime import service as execution_service
from app.workflow.runtime.schemas import ArtifactDetail, ArtifactSummary

router = APIRouter(tags=["Workflow Artifacts"])

_ARTIFACT_NOT_FOUND = {"model": ErrorResponse, "description": "No artifact exists with this id."}
_EXECUTION_NOT_FOUND = {"model": ErrorResponse, "description": "No execution exists with this id."}
_CHECKSUM_MISMATCH = {
    "model": ErrorResponse,
    "description": "The on-disk file no longer matches the recorded checksum — a real finding, not served silently.",
}
_FILE_MISSING = {
    "model": ErrorResponse,
    "description": "The file backing this artifact no longer exists on disk. Run directories can be cleaned up; the database record outliving the file is expected.",
}


def _get_artifact_or_404(db: Session, artifact_id: uuid.UUID):
    artifact = artifacts_service.get_artifact(db, artifact_id)
    if artifact is None:
        raise error(404, f"Artifact '{artifact_id}' not found", code="NOT_FOUND")
    return artifact


@router.get(
    "/api/workflow/executions/{execution_id}/artifacts",
    response_model=list[ArtifactSummary],
    summary="List artifacts produced by an execution",
    response_description="Every artifact registered under this execution — grouped-ready: producing step_name and step_execution_id are included so the UI can group without another call.",
    operation_id="list_execution_artifacts",
    responses={404: _EXECUTION_NOT_FOUND},
)
def list_execution_artifacts(execution_id: uuid.UUID, db: Session = Depends(get_db)):
    execution = execution_service.get_execution(db, execution_id)
    if execution is None:
        raise error(404, f"Execution '{execution_id}' not found", code="NOT_FOUND")
    artifacts = artifacts_service.list_execution_artifacts(db, execution_id)
    return [artifacts_service.to_artifact_summary(db, a) for a in artifacts]


@router.get(
    "/api/workflow/artifacts/{artifact_id}",
    response_model=ArtifactDetail,
    summary="Get one artifact's metadata",
    response_description="Metadata plus the resolved local path and whether the file currently exists on disk.",
    operation_id="get_artifact",
    responses={404: _ARTIFACT_NOT_FOUND},
)
def get_artifact(artifact_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Does **not** re-verify the checksum — this is metadata-only, and must
    keep working even for an artifact whose file has since been removed
    (docs/20 Part E). Use `/content` or `/download` to read the file itself,
    which do verify.
    """
    artifact = _get_artifact_or_404(db, artifact_id)
    return artifacts_service.to_artifact_detail(db, artifact)


@router.get(
    "/api/workflow/artifacts/{artifact_id}/content",
    summary="Get an artifact's parsed JSON content",
    response_description="The parsed JSON body, for inline viewing.",
    operation_id="get_artifact_content",
    responses={
        404: _FILE_MISSING,
        409: _CHECKSUM_MISMATCH,
        413: {"model": ErrorResponse, "description": f"The file exceeds the inline size limit ({settings.artifact_inline_max_bytes} bytes)."},
        415: {"model": ErrorResponse, "description": "The artifact file is not valid JSON."},
    },
)
def get_artifact_content(artifact_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Verifies the on-disk checksum before parsing. Returns the file's own
    JSON body directly (not wrapped) so the UI can render it as-is.
    """
    artifact = _get_artifact_or_404(db, artifact_id)
    try:
        artifacts_service.verify_on_disk(artifact)
    except artifacts_service.ArtifactFileMissing as exc:
        raise error(404, f"Artifact file is missing: {exc}", code="ARTIFACT_FILE_MISSING") from exc
    except artifacts_service.ArtifactChecksumMismatch as exc:
        raise error(
            409,
            f"On-disk file no longer matches the recorded checksum ({exc}).",
            code="CHECKSUM_MISMATCH",
        ) from exc

    path = local_path_from_uri(artifact.uri)
    size = path.stat().st_size
    if size > settings.artifact_inline_max_bytes:
        raise error(
            413,
            f"Artifact is {size} bytes, over the {settings.artifact_inline_max_bytes}-byte inline limit. Use /download instead.",
            code="ARTIFACT_TOO_LARGE",
        )

    text = path.read_text(encoding="utf-8-sig")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise error(415, f"Artifact is not valid JSON: {exc}", code="NOT_JSON") from exc

    return Response(content=json.dumps(parsed), media_type="application/json")


@router.get(
    "/api/workflow/artifacts/{artifact_id}/download",
    summary="Download an artifact's raw file",
    response_description="The raw file, with a Content-Disposition attachment header. Works regardless of size or content type.",
    operation_id="download_artifact",
    responses={404: _FILE_MISSING, 409: _CHECKSUM_MISMATCH},
)
def download_artifact(artifact_id: uuid.UUID, db: Session = Depends(get_db)):
    artifact = _get_artifact_or_404(db, artifact_id)
    try:
        artifacts_service.verify_on_disk(artifact)
    except artifacts_service.ArtifactFileMissing as exc:
        raise error(404, f"Artifact file is missing: {exc}", code="ARTIFACT_FILE_MISSING") from exc
    except artifacts_service.ArtifactChecksumMismatch as exc:
        raise error(
            409,
            f"On-disk file no longer matches the recorded checksum ({exc}).",
            code="CHECKSUM_MISMATCH",
        ) from exc

    path = local_path_from_uri(artifact.uri)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")
