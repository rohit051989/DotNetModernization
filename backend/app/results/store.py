"""Result artifacts in the database (app.results): copied when a step registers them, pruned to the newest
RESULTS_KEEP of each kind.

A result artifact is one a view reads: the repository page's tabs, the Overview's figures, the estate's views. Raw
outputs no view needs (SARIF exports, logs, timing profiles) stay in the run folder only. Contents are stored once per
checksum, so a step carried forward into a new execution, or a rescan that finds nothing new, costs nothing more.
"""
import datetime
import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.auth import machine
from app.config import settings
from app.workflow.adapters.base import local_path_from_uri

# What the repository page and the estate read. Everything else stays local.
REPOSITORY_TYPES = (
    "repository-inventory",
    "solution-project-inventory",
    "application-fingerprint",
    "entry-point-inventory",
    "outbound-invocation-inventory",
    "dependency-assessment",
    "dependency-hierarchy",
    "item-occurrences",
    "test-coverage",
    "impact-analysis",
)
ESTATE_TYPES = ("endpoint-register", "package-estate", "dependency-graph", "context-map", "integration-map",
                "soap-backend-compatibility")
RESULT_TYPES = REPOSITORY_TYPES + ESTATE_TYPES


def head(content) -> dict:
    """The top-level fields other than lists: summaries, counts, versions. What a view's header and the Overview
    read without opening the lists."""
    if not isinstance(content, dict):
        return {}
    return {k: v for k, v in content.items() if not isinstance(v, list)}


def scope(db: Session, job_execution_id: uuid.UUID) -> tuple[uuid.UUID | None, str | None]:
    """The repository and engagement a job execution ran for, from its parameters."""
    execution = db.get(models.WfJobExecution, job_execution_id)
    instance = db.get(models.WfJobInstance, execution.job_instance_id) if execution else None
    parameters = (instance.parameters or {}) if instance else {}
    repository_id = parameters.get("repository_id")
    try:
        repository_id = uuid.UUID(str(repository_id)) if repository_id else None
    except ValueError:
        repository_id = None
    engagement_id = parameters.get("engagement_id")
    if repository_id and not engagement_id:
        repository = db.get(models.Repository, repository_id)
        engagement_id = repository.engagement_id if repository else None
    return repository_id, engagement_id


def is_stored(db: Session, artifact_id: uuid.UUID) -> bool:
    return db.get(models.ResultArtifact, artifact_id) is not None


def publish(db: Session, artifact: models.WfArtifact, content=None, prune_after: bool = True) -> bool:
    """Copies a result artifact into the database: its content (read from its file unless given) once per checksum,
    and the record of which repository's or engagement's it is. False when it is not a result type, or its file
    cannot be read here. Then prunes that kind to the newest RESULTS_KEEP."""
    if artifact.artifact_type not in RESULT_TYPES:
        return False
    if is_stored(db, artifact.id):
        return True
    stored = db.get(models.ResultContent, artifact.checksum)
    if stored is None:
        if content is None:
            try:
                content = json.loads(local_path_from_uri(artifact.uri).read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                return False
        db.add(models.ResultContent(checksum=artifact.checksum, content=content, head=head(content),
                                    size_bytes=artifact.size_bytes))
        db.flush()
    repository_id, engagement_id = scope(db, artifact.job_execution_id)
    db.add(models.ResultArtifact(
        artifact_id=artifact.id, checksum=artifact.checksum, artifact_type=artifact.artifact_type,
        repository_id=repository_id if artifact.artifact_type in REPOSITORY_TYPES else None,
        engagement_id=engagement_id, job_execution_id=artifact.job_execution_id,
        created_at=artifact.created_at or datetime.datetime.now(datetime.timezone.utc),
        stored_by_host=machine.hostname()))
    db.flush()
    if prune_after:
        prune(db, artifact.artifact_type,
              repository_id=repository_id if artifact.artifact_type in REPOSITORY_TYPES else None,
              engagement_id=engagement_id if artifact.artifact_type in ESTATE_TYPES else None)
    return True


def prune(db: Session, artifact_type: str, repository_id: uuid.UUID | None = None, engagement_id: str | None = None,
          keep: int | None = None) -> int:
    """Removes all but the newest `keep` (RESULTS_KEEP) of one kind, for one repository or (estate kinds) one
    engagement, and any content no longer referenced. Returns how many were removed. The run folders are untouched."""
    keep = settings.results_keep if keep is None else keep
    if repository_id is None and engagement_id is None:
        return 0
    column, value = ("repository_id", repository_id) if repository_id is not None else ("engagement_id", engagement_id)
    removed = db.execute(text(f"""
        delete from result_artifacts where artifact_id in (
            select artifact_id from (
                select artifact_id, row_number() over (order by created_at desc, artifact_id desc) as n
                from result_artifacts where {column} = :value and artifact_type = :type
            ) ranked where n > :keep)
    """), {"value": value, "type": artifact_type, "keep": max(keep, 1)}).rowcount
    if removed:
        db.execute(text("""
            delete from result_contents c
            where not exists (select 1 from result_artifacts a where a.checksum = c.checksum)
        """))
    return removed or 0


def latest(db: Session, repository_id: uuid.UUID, artifact_type: str) -> models.ResultArtifact | None:
    return (db.query(models.ResultArtifact)
            .filter(models.ResultArtifact.repository_id == repository_id, models.ResultArtifact.artifact_type == artifact_type)
            .order_by(models.ResultArtifact.created_at.desc(), models.ResultArtifact.artifact_id.desc())
            .first())


def latest_estate(db: Session, engagement_id: str, step_execution_id: uuid.UUID | None = None) -> dict[str, models.ResultArtifact]:
    """The estate artifacts of one run (the step execution), else the newest of each kind for the engagement."""
    query = db.query(models.ResultArtifact).filter(models.ResultArtifact.engagement_id == engagement_id,
                                                   models.ResultArtifact.artifact_type.in_(ESTATE_TYPES))
    if step_execution_id is not None:
        ids = [a.id for a in db.query(models.WfArtifact.id).filter(models.WfArtifact.step_execution_id == step_execution_id)]
        query = query.filter(models.ResultArtifact.artifact_id.in_(ids))
    found: dict[str, models.ResultArtifact] = {}
    for row in query.order_by(models.ResultArtifact.created_at.desc(), models.ResultArtifact.artifact_id.desc()):
        found.setdefault(row.artifact_type, row)
    return found


def content(db: Session, artifact_id: uuid.UUID):
    """The stored content of an artifact, or None when it is not in the database."""
    return db.execute(text("""
        select c.content from result_artifacts a join result_contents c on c.checksum = a.checksum
        where a.artifact_id = :a
    """), {"a": artifact_id}).scalar()


def stored_head(db: Session, artifact_id: uuid.UUID) -> dict | None:
    return db.execute(text("""
        select c.head from result_artifacts a join result_contents c on c.checksum = a.checksum
        where a.artifact_id = :a
    """), {"a": artifact_id}).scalar()
