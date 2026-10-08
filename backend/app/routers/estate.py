"""The Estate tab's API — lifecycle step 11, 31-DEPENDENCY-AND-CONTEXT-MAP.md Part H.

The register, package estate, dependency graph, context map and integration
map are read from the newest completed run's artifacts, so a view is always one
consistent snapshot with its coverage. Endpoint annotations and the estate
settings (the production environment) are human data, read and written here
live; they take effect on the next run.
"""

import datetime
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.workflow.adapters.base import local_path_from_uri

router = APIRouter(prefix="/api/engagements", tags=["Estate"])

STEP_NAME = "dependency-and-context-map"
ARTIFACT_TYPES = ("endpoint-register", "package-estate", "dependency-graph", "context-map", "integration-map")
ConversationStatus = Literal["not_started", "in_progress", "agreed", "resolved", "not_required"]

_NOT_FOUND = {"model": ErrorResponse, "description": "No engagement exists with this id."}


class AnnotationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owning_team: str | None = None
    contact: str | None = None
    conversation_status: ConversationStatus = "not_started"
    target_date: datetime.date | None = None
    notes: str | None = None
    served_by_repository: str | None = Field(
        None,
        description="Slug of the engagement's repository that serves this host. HTTP calls to the host are then matched "
        "against that repository's routes on the next run. Null: not known.",
    )
    updated_by: str | None = Field(None, description="Who made the change. Free text until authentication exists.")


class AnnotationOut(AnnotationIn):
    host: str
    updated_at: datetime.datetime


DEFAULT_DEPLOY_PARAMETER_GLOBS = ["**/SetParam*.xml", "**/SetParameters*.xml"]


class EstateSettingsIn(BaseModel):
    """Only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")

    production_environment: str | None = Field(
        default=None,
        description="The environment, as step 5 names it from configuration and SetParameters file names "
        "(appsettings.Production.json, SetParamFiles/PROD/SetParam.xml), whose host names a service in the endpoint "
        "register. Null: group by the host as found.",
    )
    deploy_parameter_globs: list[str] | None = Field(
        default=None,
        description="Where Web Deploy SetParameters files are, as repository-relative globs (steps 3 and 5). "
        "Null or empty: the defaults, **/SetParam*.xml and **/SetParameters*.xml. Takes effect on the next scan.",
    )


class EstateSettingsOut(BaseModel):
    production_environment: str | None
    deploy_parameter_globs: list[str] = Field(description="The globs in force — the defaults when none are set.")
    deploy_parameter_globs_default: bool = Field(description="True when no globs are set and the defaults apply.")
    environments: list[str] = Field(description="Every environment step 5 found in the estate's configuration, for choosing.")
    repositories: list[str] = Field(description="The engagement's repository slugs, for served_by_repository.")


class EstateRunOut(BaseModel):
    step_execution_id: str
    job_execution_id: str
    completed_at: datetime.datetime | None
    exit_message: str | None


class EstateOut(BaseModel):
    engagement_id: str
    run: EstateRunOut | None = Field(description="The newest completed step 11 run; null if it has never run for this engagement.")
    artifacts: dict[str, Any] = Field(
        description="endpoint-register, package-estate, dependency-graph and context-map, as that run wrote them. Each carries coverage."
    )
    annotations: list[AnnotationOut] = Field(description="Every host's annotation, live — including hosts no longer called.")
    settings: EstateSettingsOut = Field(description="The estate settings, live: the next run uses them.")


def _engagement(db: Session, engagement_id: str) -> models.Engagement:
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None or engagement.deleted_at is not None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    return engagement


def _repository_slugs(db: Session, engagement_id: str) -> dict:
    """id -> slug of the engagement's live repositories."""
    return {
        r.id: r.slug
        for r in db.query(models.Repository).filter(models.Repository.engagement_id == engagement_id,
                                                    models.Repository.deleted_at.is_(None))
    }


def _annotation_out(a: models.EndpointAnnotation, slugs: dict) -> AnnotationOut:
    return AnnotationOut(host=a.host, owning_team=a.owning_team, contact=a.contact, conversation_status=a.conversation_status,
                         target_date=a.target_date, notes=a.notes, served_by_repository=slugs.get(a.served_by_repository_id),
                         updated_by=a.updated_by, updated_at=a.updated_at)


def _settings_out(db: Session, engagement: models.Engagement, slugs: dict) -> EstateSettingsOut:
    environments = db.execute(text("""
        select distinct b->>'environment'
        from outbound_invocations o
        join repositories r on r.id = o.repository_id
        cross join lateral jsonb_array_elements(o.environment_bindings) b
        where r.engagement_id = :e and r.deleted_at is null and b->>'environment' is not null
    """), {"e": engagement.id}).scalars().all()
    return EstateSettingsOut(production_environment=engagement.production_environment,
                             deploy_parameter_globs=engagement.deploy_parameter_globs or DEFAULT_DEPLOY_PARAMETER_GLOBS,
                             deploy_parameter_globs_default=not engagement.deploy_parameter_globs,
                             environments=sorted(environments, key=str.lower), repositories=sorted(slugs.values()))


@router.get(
    "/{engagement_id}/estate",
    response_model=EstateOut,
    summary="Get the engagement's estate view",
    response_description="The newest step 11 run's artifacts, with the endpoint annotations.",
    operation_id="get_engagement_estate",
    responses={404: _NOT_FOUND},
)
def get_estate(engagement_id: str, db: Session = Depends(get_db)):
    engagement = _engagement(db, engagement_id)
    row = db.execute(text("""
        select s.id, s.job_execution_id, s.ended_at, s.exit_message
        from wf_step_executions s
        join wf_job_executions j on j.id = s.job_execution_id
        join wf_job_instances i on i.id = j.job_instance_id
        where s.step_name = :step and i.parameters->>'engagement_id' = :e
          and s.batch_status = 'COMPLETED' and s.exit_status = 'COMPLETED' and not s.carried_forward
        order by s.ended_at desc limit 1
    """), {"step": STEP_NAME, "e": engagement_id}).first()

    artifacts: dict[str, Any] = {}
    run = None
    if row is not None:
        run = EstateRunOut(step_execution_id=str(row.id), job_execution_id=str(row.job_execution_id),
                           completed_at=row.ended_at, exit_message=row.exit_message)
        for artifact in db.query(models.WfArtifact).filter(models.WfArtifact.step_execution_id == row.id):
            if artifact.artifact_type in ARTIFACT_TYPES:
                try:
                    artifacts[artifact.artifact_type] = json.loads(local_path_from_uri(artifact.uri).read_text(encoding="utf-8"))
                except OSError:
                    continue

    annotations = (
        db.query(models.EndpointAnnotation)
        .filter(models.EndpointAnnotation.engagement_id == engagement_id)
        .order_by(models.EndpointAnnotation.host)
        .all()
    )
    slugs = _repository_slugs(db, engagement_id)
    return EstateOut(engagement_id=engagement_id, run=run, artifacts=artifacts,
                     annotations=[_annotation_out(a, slugs) for a in annotations], settings=_settings_out(db, engagement, slugs))


@router.put(
    "/{engagement_id}/estate/settings",
    response_model=EstateSettingsOut,
    summary="Set the engagement's estate settings",
    response_description="The settings as stored, with the environments and repositories to choose from.",
    operation_id="put_estate_settings",
    responses={404: _NOT_FOUND},
)
def put_settings(engagement_id: str, payload: EstateSettingsIn, db: Session = Depends(get_db)):
    """The production environment groups the endpoint register by that
    environment's host (Part C1); the next step 11 run uses it. The
    SetParameters globs say where steps 3 and 5 look for Web Deploy
    parameter files; the next scan uses them. Only the fields sent change."""
    engagement = _engagement(db, engagement_id)
    if "production_environment" in payload.model_fields_set:
        value = (payload.production_environment or "").strip()
        engagement.production_environment = value or None
    if "deploy_parameter_globs" in payload.model_fields_set:
        globs = [g.strip() for g in payload.deploy_parameter_globs or [] if g.strip()]
        engagement.deploy_parameter_globs = globs or None
    engagement.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(engagement)
    return _settings_out(db, engagement, _repository_slugs(db, engagement_id))


@router.put(
    "/{engagement_id}/estate/annotations/{host}",
    response_model=AnnotationOut,
    summary="Create or update one host's endpoint annotation",
    response_description="The annotation as stored.",
    operation_id="put_endpoint_annotation",
    responses={404: _NOT_FOUND},
)
def put_annotation(engagement_id: str, host: str, payload: AnnotationIn, db: Session = Depends(get_db)):
    """Keyed by the register's host, never an invocation id, so it survives
    rescans (Part C4). A host no run calls any more keeps its annotation and
    shows as no longer called."""
    _engagement(db, engagement_id)
    host = host.strip().lower()
    if not host:
        raise error(422, "host is required", code="INVALID_HOST")
    slugs = _repository_slugs(db, engagement_id)
    served_by = None
    if payload.served_by_repository:
        served_by = next((rid for rid, slug in slugs.items() if slug == payload.served_by_repository), None)
        if served_by is None:
            raise error(422, f"No repository '{payload.served_by_repository}' in engagement '{engagement_id}'",
                        field="served_by_repository", code="UNKNOWN_REPOSITORY")
    annotation = db.get(models.EndpointAnnotation, (engagement_id, host))
    if annotation is None:
        annotation = models.EndpointAnnotation(engagement_id=engagement_id, host=host)
        db.add(annotation)
    for field, value in payload.model_dump(exclude={"served_by_repository"}).items():
        setattr(annotation, field, value)
    annotation.served_by_repository_id = served_by
    annotation.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(annotation)
    return _annotation_out(annotation, slugs)
