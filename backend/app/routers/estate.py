"""The Estate tab's API — lifecycle step dependency-and-context-map, 31-DEPENDENCY-AND-CONTEXT-MAP.md Part H.

The register, package estate, dependency graph, context map, integration
map and SOAP backend compatibility report are read from the newest completed
run's artifacts, so a view is always one consistent snapshot with its
coverage. Endpoint annotations and the estate settings (the production
environment) are human data, read and written here live; they take effect on
the next run. The SOAP report's matrix confirmations are read live too, from
the WCF client runtime and platform matrix files (Part J), with the probe
results recorded on their entries: a person confirms an entry there, by pull
request, and the report stops being a draft once every entry it rests on is
confirmed and no probe contradicts one.
"""

import csv
import io

import datetime
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.estate import engagement_matrix, soap_compatibility, wcf_matrix
from app.workflow.adapters.base import local_path_from_uri

router = APIRouter(prefix="/api/engagements", tags=["Estate"])

STEP_NAME = "dependency-and-context-map"
ARTIFACT_TYPES = ("endpoint-register", "package-estate", "dependency-graph", "context-map", "integration-map",
                  "soap-backend-compatibility")
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
    target_wcf_client_version: str | None = Field(
        default=None,
        pattern=r"^[0-9]+(\.[0-9]+){1,3}(-[0-9A-Za-z.-]+)?$",
        description="The WCF client package version (System.ServiceModel.*) the engagement targets, e.g. 8.1.2. The SOAP "
        "report flags matrix entries whose probe evidence covers an older one. Null: the version the WCF client matrices "
        "record for the target framework. Takes effect at once.",
    )


class EstateSettingsOut(BaseModel):
    production_environment: str | None
    target_wcf_client_version: str | None = Field(description="As set; null means the matrices' version for the target framework.")
    target_wcf_client_version_effective: str | None = Field(description="The version in force: as set, else the matrices'.")
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
    effective = engagement.target_wcf_client_version or wcf_matrix.target_wcf_client(
        soap_compatibility.load_matrix(), engagement.target_framework)
    return EstateSettingsOut(production_environment=engagement.production_environment,
                             target_wcf_client_version=engagement.target_wcf_client_version,
                             target_wcf_client_version_effective=effective,
                             deploy_parameter_globs=engagement.deploy_parameter_globs or DEFAULT_DEPLOY_PARAMETER_GLOBS,
                             deploy_parameter_globs_default=not engagement.deploy_parameter_globs,
                             environments=sorted(environments, key=str.lower), repositories=sorted(slugs.values()))


def _latest_run(db: Session, engagement_id: str) -> tuple[Any, dict[str, Any]]:
    """The newest completed step 11 run of the engagement, and its artifacts."""
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
    if row is not None:
        for artifact in db.query(models.WfArtifact).filter(models.WfArtifact.step_execution_id == row.id):
            if artifact.artifact_type in ARTIFACT_TYPES:
                try:
                    artifacts[artifact.artifact_type] = json.loads(local_path_from_uri(artifact.uri).read_text(encoding="utf-8"))
                except OSError:
                    continue
    return row, artifacts


def _soap_report(report: dict, annotations: list, engagement: models.Engagement, applied: dict | None = None) -> dict:
    """The run's SOAP report with what is live, read from the matrix versions
    the run used: each matrix entry's confirmation, probe results and what its
    evidence covers — runtime and platform alike — the matrices' provenance,
    and each host's owning team as a person annotated it. `applied` is the
    engagement's own probes and confirmations (engagement_matrix.overlay),
    applied on top of the shipped matrices; an engagement confirmation or probe
    whose evidence is gone or changed shows as evidence missing.

    An entry a probe contradicts is shown as under review, never as its
    unrevised verdict, and every total counts it apart
    (soap_compatibility.review). An entry whose evidence covers an older WCF
    client than the engagement targets is flagged. readyForClient only when
    every entry the report rests on is confirmed, none is contradicted, none
    has evidence older than the targeted WCF client or missing, and the run
    used the newest matrices."""
    matrix = soap_compatibility.load_matrix(report.get("matrixVersion")) or soap_compatibility.load_matrix()
    platform = wcf_matrix.load("platform", report.get("platformMatrixVersion")) or wcf_matrix.load("platform")
    newest = {kind: (wcf_matrix.load(kind) or {}).get("matrixVersion") for kind in wcf_matrix.KINDS}
    # The shipped matrices, with this engagement's own probes and confirmations (client data, in the
    # database) applied on top: 29 C10, the probe evidence boundary.
    entries = {}
    for kind, m in (("support", matrix), ("platform", platform)):
        entries.update(engagement_matrix.apply(kind, {e["id"]: e for e in (m or {}).get("entries", [])}, applied))
    kinds = {e["id"]: kind for kind, m in (("support", matrix), ("platform", platform)) for e in (m or {}).get("entries", [])}
    owners = {a.host: a.owning_team for a in annotations}
    target_wcf = engagement.target_wcf_client_version or wcf_matrix.target_wcf_client(matrix, engagement.target_framework)
    used, unconfirmed = set(), set()

    def contradictions(entry_id: str) -> list[str]:
        return wcf_matrix.probe_contradictions(kinds[entry_id], entries[entry_id])

    def overlay(verdict: dict) -> dict:
        entry = entries.get(verdict.get("matrixEntry") or "")
        confirmation = (entry or {}).get("confirmation") or {}
        if entry:
            used.add(entry["id"])
            if confirmation.get("status") != "confirmed":
                unconfirmed.add(entry["id"])
        return {**verdict, "matrixConfirmed": confirmation.get("status") == "confirmed" if entry else None,
                "confirmedBy": confirmation.get("by"), "confirmedOn": confirmation.get("on"),
                "sources": (entry or {}).get("sources", []), "probes": (entry or {}).get("probes", []),
                "probeContradictions": contradictions(entry["id"]) if entry else [],
                "confirmationSource": "engagement" if isinstance(confirmation.get("source"), dict) else "shipped" if entry else None,
                "evidenceMissing": engagement_matrix.evidence_missing(entry) if entry else False,
                "evidenceCovers": wcf_matrix.evidence_covers(entry) if entry else None,
                "evidencePredatesTarget": wcf_matrix.evidence_predates(entry, target_wcf) if entry else False}

    hosts = []
    for host in report.get("hosts", []):
        callers = [{**caller, "environments": [{**env, "runtime": overlay(env["runtime"]), "platform": overlay(env["platform"])}
                                               for env in caller["environments"]]}
                   for caller in host["callers"]]
        hosts.append({**host, "owningTeam": owners.get(host["host"]), "callers": callers})
    contradicted = {i: contradictions(i) for i in sorted(used) if contradictions(i)}
    missing_evidence = sorted(i for i in used if engagement_matrix.evidence_missing(entries[i]))
    hosts = soap_compatibility.review(hosts, contradicted)
    predating = sorted(i for i in used if wcf_matrix.evidence_predates(entries[i], target_wcf))
    unprobed = sorted(i for i in used if wcf_matrix.evidence_covers(entries[i]) is None)
    # The versions the run recorded, not the files loaded: a run before soap-backend-compatibility 1.1.0 recorded
    # no platform version, and is older than any.
    stale = {kind: {"run": run, "newest": newest[kind]}
             for kind, run in (("support", report.get("matrixVersion")), ("platform", report.get("platformMatrixVersion")))
             if newest[kind] and (run is None or wcf_matrix.version_key(run) < wcf_matrix.version_key(newest[kind]))}
    return {
        **report,
        "summary": soap_compatibility.summarize(hosts),
        "hosts": hosts,
        "matrix": {
            "version": (matrix or {}).get("matrixVersion"),
            "runVersion": report.get("matrixVersion"),
            "platformVersion": (platform or {}).get("matrixVersion"),
            "newerMatrices": stale,
            "sources": (matrix or {}).get("sources", []),
            "platformSources": (platform or {}).get("sources", []),
            "targetWcfClientVersion": target_wcf,
            "targetWcfClientVersionSource": "engagement" if engagement.target_wcf_client_version else "matrix",
            "entriesUsed": sorted(used),
            "unconfirmedEntries": sorted(unconfirmed),
            "contradictedEntries": sorted(contradicted),
            "evidencePredatesTarget": predating,
            "unprobedEntries": unprobed,
            "evidenceMissingEntries": missing_evidence,
            "entries": {i: {"kind": kinds[i], "verdict": entries[i]["verdict"], "basis": entries[i]["basis"],
                            "probes": entries[i].get("probes", []), "probeContradictions": contradicted.get(i, []),
                            "evidenceCovers": wcf_matrix.evidence_covers(entries[i]),
                            "evidencePredatesTarget": i in predating, "revision": entries[i].get("revision"),
                            "confirmation": entries[i].get("confirmation")}
                        for i in sorted(used)},
            "readyForClient": (bool(matrix) and bool(platform) and not unconfirmed and not contradicted and not predating
                               and not stale and not missing_evidence),
        },
    }


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
    row, artifacts = _latest_run(db, engagement_id)
    run = None
    if row is not None:
        run = EstateRunOut(step_execution_id=str(row.id), job_execution_id=str(row.job_execution_id),
                           completed_at=row.ended_at, exit_message=row.exit_message)

    annotations = (
        db.query(models.EndpointAnnotation)
        .filter(models.EndpointAnnotation.engagement_id == engagement_id)
        .order_by(models.EndpointAnnotation.host)
        .all()
    )
    slugs = _repository_slugs(db, engagement_id)
    if "soap-backend-compatibility" in artifacts:
        artifacts["soap-backend-compatibility"] = _soap_report(artifacts["soap-backend-compatibility"], annotations, engagement,
                                                              engagement_matrix.overlay(db, engagement_id))
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
    if "target_wcf_client_version" in payload.model_fields_set:
        engagement.target_wcf_client_version = (payload.target_wcf_client_version or "").strip() or None
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


SOAP_CSV_COLUMNS = (
    "backend_host", "backend_owner", "owning_team", "served_by", "calling_application", "project", "contract", "environment",
    "address", "binding", "security_mode", "credential_type", "security_source", "runtime_verdict", "runtime_reasons",
    "matrix_entry", "matrix_entry_confirmed", "platform_verdict", "platform_reasons", "platform_matrix_entry",
    "platform_matrix_entry_confirmed", "probe_results", "probe_contradictions", "evidence_covers", "evidence_predates_target",
    "what_must_change", "who_changes_it",
    "target_framework", "matrix_version", "matrix_source",
)
WHO = {"we": "this migration (calling application)", "backend_owner": "backend owner",
       "we_or_backend_owner": "this migration or the backend owner (not yet known which)"}
CONFIRMED = {True: "yes", False: "NO - awaiting confirmation", None: ""}


def _confirmed_text(verdict: dict) -> str:
    if verdict.get("evidenceMissing"):
        return "NO - evidence missing"
    text = CONFIRMED[verdict.get("matrixConfirmed")]
    return f"{text} (this engagement)" if verdict.get("matrixConfirmed") and verdict.get("confirmationSource") == "engagement" else text
UNDER_REVIEW_TEXT = "contradicted by probe - under review"


def _verdict_text(verdict: str | None) -> str:
    return UNDER_REVIEW_TEXT if verdict == soap_compatibility.UNDER_REVIEW else verdict or ""


def _covers_text(env: dict) -> str:
    parts = []
    for side in ("runtime", "platform"):
        covers = env[side].get("evidenceCovers")
        if covers:
            parts.append(f"{side}: WCF client {covers['wcfClient']} on .NET {', '.join(covers['runtimes'])}")
    return " | ".join(parts)


def _probe_key(probe: dict) -> str | None:
    """A probe's identity: its evidence path (platform samples), its evidence
    reference (a client engagement's, kept with that engagement), or its reason."""
    ref = probe.get("evidenceRef")
    return probe.get("evidence") or (f"{ref['engagement']}/{ref['id']}" if ref else None) or probe.get("reason")


def _probe_results(env: dict) -> str:
    """The probes behind both of an environment's entries, once each: a probe
    is recorded on its runtime and its platform entry alike. A client
    engagement's probe carries no message: its exception type and a reference."""
    seen, results = set(), []
    for probe in env["runtime"].get("probes", []) + env["platform"].get("probes", []):
        key = _probe_key(probe)
        if key in seen:
            continue
        seen.add(key)
        if probe.get("outcome") == "not_probed":
            results.append(f"not probed: {probe.get('reason')}")
        else:
            attribution = f", attributed to the {probe['attribution']}" if probe.get("attribution") else ""
            detail = probe.get("summary") or probe.get("errorType") or ""
            if probe.get("evidenceRef"):
                detail = f"{detail} (evidence {_probe_key(probe)}, kept with the engagement)".strip()
            results.append(f"{probe.get('scenario')} on {probe.get('probedOn')}: {probe.get('outcome')}{attribution} - {detail}")
    return " | ".join(results)


def soap_csv(report: dict, target_framework: str | None) -> str:
    """The client-facing export: one row per backend host, calling application
    and environment, each carrying its provenance."""
    chart = next((src for src in report["matrix"]["sources"] if src["id"].startswith("chart-")), {})
    source = f"{chart.get('title', '')} {chart.get('version', '')} ({chart.get('url', '')})".strip()
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(SOAP_CSV_COLUMNS)
    for host in report["hosts"]:
        owner = f"this migration ({', '.join(host['servedBy'])})" if host["backendOwner"] == "this_migration" else "another team"
        for caller in host["callers"]:
            for env in caller["environments"]:
                changes = env["changes"] or [{"who": "", "change": UNDER_REVIEW_TEXT if env.get("underReview") else "no change"}]
                writer.writerow([
                    host["host"], owner, host.get("owningTeam") or "", ", ".join(host["servedBy"]), caller["application"],
                    caller["projectPath"], caller.get("contract") or "", env["environment"], env.get("address") or "",
                    env.get("binding") or "", env.get("securityMode") or "", env.get("credentialType") or "",
                    env.get("securitySource") or "", _verdict_text(env["runtime"]["verdict"]), " | ".join(env["runtime"]["reasons"]),
                    env["runtime"].get("matrixEntry") or "", _confirmed_text(env["runtime"]),
                    _verdict_text(env["platform"]["verdict"]), " | ".join(env["platform"]["reasons"]),
                    env["platform"].get("matrixEntry") or "", _confirmed_text(env["platform"]),
                    _probe_results(env),
                    " | ".join(env["runtime"].get("probeContradictions", []) + env["platform"].get("probeContradictions", [])),
                    _covers_text(env),
                    "YES - re-probe" if env["runtime"].get("evidencePredatesTarget") or env["platform"].get("evidencePredatesTarget") else "",
                    " | ".join(c["change"] for c in changes), " | ".join(WHO.get(c["who"], "") for c in changes),
                    target_framework or "", report["matrix"]["version"] or "", source,
                ])
    return buffer.getvalue()


@router.get(
    "/{engagement_id}/estate/soap-compatibility.csv",
    response_class=Response,
    summary="Export the SOAP backend compatibility report as CSV",
    response_description="One row per backend host, calling application and environment, with both verdicts, what must change "
                         "and who changes it. The file name ends in -DRAFT while any matrix entry it rests on is unconfirmed, "
                         "contradicted by a probe, or has evidence older than the targeted WCF client.",
    operation_id="export_soap_compatibility",
    responses={200: {"content": {"text/csv": {}}}, 404: _NOT_FOUND,
               409: {"model": ErrorResponse, "description": "The estate has not been consolidated with the SOAP report yet."}},
)
def export_soap_compatibility(engagement_id: str, db: Session = Depends(get_db)):
    engagement = _engagement(db, engagement_id)
    _, artifacts = _latest_run(db, engagement_id)
    if "soap-backend-compatibility" not in artifacts:
        raise error(409, "No SOAP backend compatibility report yet: run the estate consolidation.", code="NOT_RUN")
    annotations = db.query(models.EndpointAnnotation).filter(models.EndpointAnnotation.engagement_id == engagement_id).all()
    report = _soap_report(artifacts["soap-backend-compatibility"], annotations, engagement, engagement_matrix.overlay(db, engagement_id))
    draft = "" if report["matrix"]["readyForClient"] else "-DRAFT"
    return Response(content=soap_csv(report, engagement.target_framework).encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="soap-backend-compatibility-{engagement_id}{draft}.csv"'})


class MatrixDecisionIn(BaseModel):
    """A person's decision, in this engagement, to confirm shipped WCF client
    matrix entries on this engagement's probe evidence (29 C10)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="The decision's own id, e.g. 'CLIENT-2026-11-02-a'.")
    by: str = Field(min_length=1, description="The person who decided.")
    on: datetime.date
    instruction: str = Field(min_length=1, description="The decision as the person gave it, verbatim.")
    entries: list[str] = Field(min_length=1, description="The shipped matrix entry ids it confirms, each named.")
    evidence: dict[str, list[str]] = Field(description="Per named entry, the ids of this engagement's probe evidence it rests on.")
    notes: dict[str, str] | None = None


class MatrixRevertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str = Field(min_length=1)
    by: str = Field(min_length=1)
    reason: str = Field(min_length=1)


@router.get(
    "/{engagement_id}/estate/matrix-confirmations",
    summary="List this engagement's own WCF client matrix confirmations and probe evidence",
    response_description="The confirmations and probes the SOAP report applies on top of the shipped matrices.",
    operation_id="get_engagement_matrix_confirmations",
    responses={404: _NOT_FOUND},
)
def get_matrix_confirmations(engagement_id: str, db: Session = Depends(get_db)):
    """Client data: kept with the engagement in this deployment's database,
    never written to a shipped matrix file."""
    _engagement(db, engagement_id)
    return engagement_matrix.overlay(db, engagement_id)


@router.post(
    "/{engagement_id}/estate/matrix-confirmations",
    status_code=201,
    summary="Record a decision confirming shipped matrix entries on this engagement's evidence",
    response_description="The entries confirmed, for this engagement only.",
    operation_id="post_engagement_matrix_decision",
    responses={404: _NOT_FOUND, 422: {"model": ErrorResponse, "description": "An entry is not named, unknown, or has no intact evidence."}},
)
def post_matrix_decision(engagement_id: str, payload: MatrixDecisionIn, db: Session = Depends(get_db)):
    """Confirms exactly the named entries, each on intact evidence of this
    engagement that bears on it. The shipped matrices are not changed."""
    _engagement(db, engagement_id)
    try:
        confirmed = engagement_matrix.record_decision(db, engagement_id, payload.model_dump())
    except ValueError as exc:
        db.rollback()
        raise error(422, str(exc), code="INVALID_DECISION") from exc
    db.commit()
    return {"confirmed": confirmed}


@router.post(
    "/{engagement_id}/estate/matrix-confirmations/revert",
    summary="Revert this engagement's confirmation of a matrix entry",
    response_description="The entry is unconfirmed for this engagement; the confirmation is kept, with who reverted it and why.",
    operation_id="revert_engagement_matrix_confirmation",
    responses={404: _NOT_FOUND, 422: {"model": ErrorResponse, "description": "The entry has no confirmation in this engagement."}},
)
def revert_matrix_confirmation(engagement_id: str, payload: MatrixRevertIn, db: Session = Depends(get_db)):
    _engagement(db, engagement_id)
    try:
        engagement_matrix.revert(db, engagement_id, payload.entry_id, payload.by, payload.reason)
    except ValueError as exc:
        db.rollback()
        raise error(422, str(exc), code="NOT_CONFIRMED") from exc
    db.commit()
    return {"reverted": payload.entry_id}
