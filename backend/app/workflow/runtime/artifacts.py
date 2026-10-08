"""Artifact read access — list, detail, content, download. See
19-SOLUTION-DISCOVERY.md-adjacent 20-WORKFLOW-OBSERVABILITY-UI.md
Part A: 'Both must verify the on-disk checksum against wf_artifacts.checksum
before returning, and respond 409 ... if they differ.'
"""

import uuid

from sqlalchemy.orm import Session

from app import models
from app.workflow.adapters.base import compute_checksum, local_path_from_uri
from app.workflow.runtime.schemas import ArtifactDetail, ArtifactSummary


def get_artifact(db: Session, artifact_id: uuid.UUID) -> models.WfArtifact | None:
    return db.get(models.WfArtifact, artifact_id)


def list_execution_artifacts(db: Session, execution_id: uuid.UUID) -> list[models.WfArtifact]:
    return (
        db.query(models.WfArtifact)
        .filter_by(job_execution_id=execution_id)
        .order_by(models.WfArtifact.created_at)
        .all()
    )


def to_artifact_summary(db: Session, artifact: models.WfArtifact) -> ArtifactSummary:
    step_execution = db.get(models.WfStepExecution, artifact.step_execution_id)
    return ArtifactSummary(
        id=artifact.id,
        artifact_type=artifact.artifact_type,
        artifact_version=artifact.artifact_version,
        size_bytes=artifact.size_bytes,
        checksum=artifact.checksum,
        step_name=step_execution.step_name if step_execution else "",
        step_execution_id=artifact.step_execution_id,
        created_at=artifact.created_at,
    )


def to_artifact_detail(db: Session, artifact: models.WfArtifact) -> ArtifactDetail:
    try:
        resolved = local_path_from_uri(artifact.uri)
        resolved_path = str(resolved)
        file_exists = resolved.is_file()
    except ValueError:
        resolved_path = None
        file_exists = False

    summary = to_artifact_summary(db, artifact)
    return ArtifactDetail(
        **summary.model_dump(),
        job_execution_id=artifact.job_execution_id,
        uri=artifact.uri,
        resolved_path=resolved_path,
        file_exists=file_exists,
        metadata=artifact.artifact_metadata,
    )


class ArtifactFileMissing(Exception):
    """The file backing this artifact record no longer exists on disk — run
    directories can be cleaned up; the database record outliving the file is
    expected, not an error (docs/20 Part E)."""


class ArtifactChecksumMismatch(Exception):
    """The on-disk file no longer matches wf_artifacts.checksum — a real
    finding (tampering, corruption, a non-deterministic producer), never
    served silently (docs/20 Part A)."""

    def __init__(self, expected: str, actual: str):
        super().__init__(f"declared {expected}, computed {actual}")
        self.expected = expected
        self.actual = actual


def verify_on_disk(artifact: models.WfArtifact) -> None:
    """Raises ArtifactFileMissing or ArtifactChecksumMismatch; returns
    normally when the file exists and matches."""
    try:
        path = local_path_from_uri(artifact.uri)
    except ValueError as exc:
        raise ArtifactFileMissing(str(exc)) from exc
    if not path.is_file():
        raise ArtifactFileMissing(f"'{path}' does not exist")
    actual = compute_checksum(artifact.uri)
    if actual != artifact.checksum:
        raise ArtifactChecksumMismatch(artifact.checksum, actual)
