"""Job-to-job precondition evaluation — see 12-JOB-DEFINITION-FORMAT.md's
'Job-to-job dependency' section. Jobs never call each other directly;
dependency is a precondition checked at launch.

`scope: all_in_wave` (used once trackB-wave exists) and other wave/application
-level scoping are not implemented — no wave or application model exists yet
in this build. Only engagement-level checks are supported today, which is
sufficient for `phase0-estate-consolidation`'s future precondition and for
`decision_approved`. Nothing currently defined uses preconditions, so this
is exercised generically rather than against a real job.
"""

from sqlalchemy.orm import Session

from app import models
from app.workflow.definition.model import JobDefinitionFile


def evaluate_preconditions(db: Session, definition: JobDefinitionFile, parameters: dict) -> list[dict]:
    """Returns errors in this API's shared shape (`field`/`message`/`code`)
    for every unmet precondition. Empty means the job may launch."""
    failures: list[dict] = []
    for pre in definition.preconditions:
        if pre.type == "job_completed":
            if not _job_completed(db, pre.job_name, parameters):
                failures.append(
                    {
                        "field": None,
                        "message": pre.description or f"job '{pre.job_name}' has not completed",
                        "code": "PRECONDITION_JOB_NOT_COMPLETED",
                    }
                )
        elif pre.type == "artifact_exists":
            if not _artifact_exists(db, pre.artifact_type):
                failures.append(
                    {
                        "field": None,
                        "message": pre.description or f"no artifact of type '{pre.artifact_type}' exists",
                        "code": "PRECONDITION_ARTIFACT_MISSING",
                    }
                )
        elif pre.type == "decision_approved":
            if not _decision_approved(db, pre.pattern_id, parameters):
                failures.append(
                    {
                        "field": None,
                        "message": pre.description or f"pattern '{pre.pattern_id}' has no approved decision",
                        "code": "PRECONDITION_DECISION_NOT_APPROVED",
                    }
                )
    return failures


def _job_completed(db: Session, job_name: str | None, parameters: dict) -> bool:
    query = (
        db.query(models.WfJobExecution)
        .join(models.WfJobInstance, models.WfJobExecution.job_instance_id == models.WfJobInstance.id)
        .filter(
            models.WfJobInstance.job_name == job_name,
            models.WfJobExecution.batch_status == "COMPLETED",
        )
    )
    engagement_id = parameters.get("engagement_id")
    if engagement_id is not None:
        query = query.filter(
            models.WfJobInstance.parameters["engagement_id"].astext == str(engagement_id)
        )
    return db.query(query.exists()).scalar()


def _artifact_exists(db: Session, artifact_type: str | None) -> bool:
    return db.query(
        db.query(models.WfArtifact).filter_by(artifact_type=artifact_type).exists()
    ).scalar()


def _decision_approved(db: Session, pattern_id: str | None, parameters: dict) -> bool:
    query = db.query(models.DecisionRecord).filter(
        models.DecisionRecord.pattern_id == pattern_id,
        models.DecisionRecord.status == "approved",
        models.DecisionRecord.deleted_at.is_(None),
    )
    engagement_id = parameters.get("engagement_id")
    if engagement_id is not None:
        query = query.filter(models.DecisionRecord.engagement_id == engagement_id)
    return db.query(query.exists()).scalar()
