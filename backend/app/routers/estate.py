"""The Estate tab's API — lifecycle step dependency-and-context-map, 31-DEPENDENCY-AND-CONTEXT-MAP.md Part H.

The register, package estate, dependency graph, context map, integration
map and SOAP backend compatibility report are read from the newest completed
run's artifacts, so a view is always one consistent snapshot with its
coverage. They are read from the database (app.results), never from the run
folder of the machine that ran the consolidation, and each view's lists are
served a page at a time (app.routers.estate_pages). Endpoint annotations and the estate settings (the production
environment) are human data, read and written here live; they take effect on
the next run. The SOAP report's matrix confirmations are read live too, from
the WCF client runtime and platform matrix files (Part J), with the probe
results recorded on their entries: a person confirms an entry there, by pull
request, and the report stops being a draft once every entry it rests on is
confirmed and no probe contradicts one.
"""

from typing import Annotated
import csv
import io

import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.auth import versions
from app.db import get_db
from app.errors import ErrorResponse, error
from app.estate import engagement_matrix, soap_compatibility, wcf_matrix
from app.results import store as results_store

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
        description="The environment, as outbound-invocation-inventory names it from configuration and SetParameters file names "
        "(appsettings.Production.json, SetParamFiles/PROD/SetParam.xml), whose host names a service in the endpoint "
        "register. Null: group by the host as found.",
    )
    deploy_parameter_globs: list[str] | None = Field(
        default=None,
        description="Where Web Deploy SetParameters files are, as repository-relative globs (application-fingerprinting and outbound-invocation-inventory). "
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
    environments: list[str] = Field(description="Every environment outbound-invocation-inventory found in the estate's configuration, for choosing.")
    repositories: list[str] = Field(description="The engagement's repository slugs, for served_by_repository.")
    version: int = Field(default=1, description="The engagement's version: send it back in If-Match when changing the settings.")


class EstateRunOut(BaseModel):
    step_execution_id: str
    job_execution_id: str
    completed_at: datetime.datetime | None
    exit_message: str | None


class RegisterCountsOut(BaseModel):
    """The register's hosts that require a backend change, with how their conversations stand (the annotations, live)."""

    backend: int
    another_team: int
    this_migration: int
    under_way: int
    not_started: int
    done: int


class EstateOut(BaseModel):
    engagement_id: str
    run: EstateRunOut | None = Field(description="The newest completed dependency-and-context-map run; null if it has never run for this engagement.")
    artifacts: dict[str, Any] = Field(
        description="Each of that run's artifacts without its lists: summary, coverage and settings it was built with. The "
                    "lists come a page at a time (/estate/...). The SOAP report's summary and matrix are live."
    )
    artifact_ids: dict[str, str] = Field(default_factory=dict, description="The artifacts' ids, by kind.")
    register_counts: RegisterCountsOut | None = None
    served_by_pending: bool = Field(default=False, description="A served-by annotation differs from what the register "
                                                               "was built with: the next run applies it.")
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
    return EstateSettingsOut(version=engagement.version, production_environment=engagement.production_environment,
                             target_wcf_client_version=engagement.target_wcf_client_version,
                             target_wcf_client_version_effective=effective,
                             deploy_parameter_globs=engagement.deploy_parameter_globs or DEFAULT_DEPLOY_PARAMETER_GLOBS,
                             deploy_parameter_globs_default=not engagement.deploy_parameter_globs,
                             environments=sorted(environments, key=str.lower), repositories=sorted(slugs.values()))


def _latest_run(db: Session, engagement_id: str, contents: bool = True) -> tuple[Any, dict[str, Any]]:
    """The newest completed dependency-and-context-map run of the engagement, and its artifacts' contents, from the
    database (app.results): the run may have been made on another machine. contents=False: the run only."""
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
    if row is not None and contents:
        for kind, stored in results_store.latest_estate(db, engagement_id, row.id).items():
            artifacts[kind] = results_store.content(db, stored.artifact_id)
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

    def overlay(verdict: dict, kind: str) -> dict:
        entry = entries.get(verdict.get("matrixEntry") or "")
        confirmation = (entry or {}).get("confirmation") or {}
        if entry:
            used.add(entry["id"])
            if confirmation.get("status") != "confirmed":
                unconfirmed.add(entry["id"])
        shown = wcf_matrix.UNDER_REVIEW if entry and contradictions(entry["id"]) else verdict.get("verdict")
        return {**verdict, "why": wcf_matrix.why(kind, shown, verdict.get("reasons"), verdict.get("matrixEntry"), entry),
                "matrixConfirmed": confirmation.get("status") == "confirmed" if entry else None,
                "confirmedBy": confirmation.get("by"), "confirmedOn": confirmation.get("on"),
                "sources": (entry or {}).get("sources", []), "probes": (entry or {}).get("probes", []),
                "probeContradictions": contradictions(entry["id"]) if entry else [],
                "confirmationSource": "engagement" if isinstance(confirmation.get("source"), dict) else "shipped" if entry else None,
                "evidenceMissing": engagement_matrix.evidence_missing(entry) if entry else False,
                "evidenceCovers": wcf_matrix.evidence_covers(entry) if entry else None,
                "evidencePredatesTarget": wcf_matrix.evidence_predates(entry, target_wcf) if entry else False}

    hosts = []
    for host in report.get("hosts", []):
        callers = [{**caller, "environments": [{**env, "runtime": overlay(env["runtime"], "support"), "platform": overlay(env["platform"], "platform")}
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
    response_description="The newest dependency-and-context-map run's artifacts, with the endpoint annotations.",
    operation_id="get_engagement_estate",
    responses={404: _NOT_FOUND},
)
def get_estate(engagement_id: str, db: Session = Depends(get_db)):
    """The run, each artifact's summary and coverage, the register's counts and the settings. Each view's lists come a
    page at a time from its own endpoint."""
    engagement = _engagement(db, engagement_id)
    row, _ = _latest_run(db, engagement_id, contents=False)
    slugs = _repository_slugs(db, engagement_id)
    run = None
    heads: dict[str, Any] = {}
    ids: dict[str, str] = {}
    counts, pending = None, False
    if row is not None:
        run = EstateRunOut(step_execution_id=str(row.id), job_execution_id=str(row.job_execution_id),
                           completed_at=row.ended_at, exit_message=row.exit_message)
        for kind, stored in results_store.latest_estate(db, engagement_id, row.id).items():
            ids[kind] = str(stored.artifact_id)
            heads[kind] = results_store.stored_head(db, stored.artifact_id)
        if "soap-backend-compatibility" in ids:
            heads["soap-backend-compatibility"] = soap_head(db, engagement, ids["soap-backend-compatibility"])
        if "endpoint-register" in ids:
            counts = _register_counts(db, engagement_id, ids["endpoint-register"])
            served = heads["endpoint-register"].get("servedByAnnotations") or {}
            pending = any(slugs.get(a.served_by_repository_id) != served.get(a.host)
                          for a in db.query(models.EndpointAnnotation).filter(models.EndpointAnnotation.engagement_id == engagement_id))
    return EstateOut(engagement_id=engagement_id, run=run, artifacts=heads, artifact_ids=ids, register_counts=counts,
                     served_by_pending=pending, settings=_settings_out(db, engagement, slugs))


def _register_counts(db: Session, engagement_id: str, artifact_id: str) -> RegisterCountsOut:
    row = db.execute(text("""
        select count(*) filter (where backend) as backend,
               count(*) filter (where backend and owner = 'this_migration') as this_migration,
               count(*) filter (where backend and status in ('in_progress', 'agreed')) as under_way,
               count(*) filter (where backend and status = 'not_started') as not_started
        from (
            select coalesce((h->>'requiresBackendChange')::boolean, false) as backend, h->>'backendChangeOwner' as owner,
                   coalesce(a.conversation_status, 'not_started') as status
            from result_artifacts r join result_contents c on c.checksum = r.checksum,
                 jsonb_array_elements(coalesce(c.content->'hosts', '[]')) h
            left join endpoint_annotations a on a.engagement_id = :e and a.host = h->>'host'
            where r.artifact_id = :a
        ) x
    """), {"e": engagement_id, "a": artifact_id}).one()
    return RegisterCountsOut(backend=row.backend, another_team=row.backend - row.this_migration,
                             this_migration=row.this_migration, under_way=row.under_way, not_started=row.not_started,
                             done=row.backend - row.under_way - row.not_started)


def soap_head(db: Session, engagement: models.Engagement, artifact_id: str) -> dict:
    """The SOAP report without its hosts, with its summary and matrix as they stand now: confirmations, probes and
    the targeted WCF client are read live, over every host, so the totals are the report's whole."""
    annotations = db.query(models.EndpointAnnotation).filter(models.EndpointAnnotation.engagement_id == engagement.id).all()
    report = _soap_report(results_store.content(db, artifact_id), annotations, engagement,
                          engagement_matrix.overlay(db, engagement.id))
    return {k: v for k, v in report.items() if k != "hosts"}


@router.put(
    "/{engagement_id}/estate/settings",
    response_model=EstateSettingsOut,
    summary="Set the engagement's estate settings",
    response_description="The settings as stored, with the environments and repositories to choose from.",
    operation_id="put_estate_settings",
    responses={404: _NOT_FOUND},
)
def put_settings(
    engagement_id: str, payload: EstateSettingsIn, db: Session = Depends(get_db),
    if_match: Annotated[str | None, Header(description="The engagement's version the edit was made on; a stale copy is refused (409 STALE_COPY).")] = None,
):
    """The production environment groups the endpoint register by that
    environment's host (Part C1); the next dependency-and-context-map run uses it. The
    SetParameters globs say where application-fingerprinting and outbound-invocation-inventory look for Web Deploy
    parameter files; the next scan uses them. Only the fields sent change."""
    engagement = _engagement(db, engagement_id)
    db.refresh(engagement, with_for_update=True)
    versions.check(db, engagement.version, if_match, "engagement", engagement_id, "this engagement's settings")
    if "production_environment" in payload.model_fields_set:
        value = (payload.production_environment or "").strip()
        engagement.production_environment = value or None
    if "deploy_parameter_globs" in payload.model_fields_set:
        globs = [g.strip() for g in payload.deploy_parameter_globs or [] if g.strip()]
        engagement.deploy_parameter_globs = globs or None
    if "target_wcf_client_version" in payload.model_fields_set:
        engagement.target_wcf_client_version = (payload.target_wcf_client_version or "").strip() or None
    engagement.version += 1
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
    "matrix_entry", "matrix_entry_confirmed", "runtime_why", "platform_verdict", "platform_reasons", "platform_matrix_entry",
    "platform_matrix_entry_confirmed", "platform_why", "probe_results", "probe_contradictions", "evidence_covers", "evidence_predates_target",
    "what_must_change", "who_changes_it",
    "target_framework", "matrix_version", "matrix_source",
)
WHO = {"we": "this migration (calling application)", "backend_owner": "backend owner",
       "we_or_backend_owner": "this migration or the backend owner (not yet known which)"}
# Confirmed: a named person reviewed the matrix entry's evidence and accepted it. Unconfirmed: nobody has yet.
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
                    env["runtime"].get("matrixEntry") or "", _confirmed_text(env["runtime"]), env["runtime"].get("why") or "",
                    _verdict_text(env["platform"]["verdict"]), " | ".join(env["platform"]["reasons"]),
                    env["platform"].get("matrixEntry") or "", _confirmed_text(env["platform"]), env["platform"].get("why") or "",
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
    confirmation_id: str | None = Field(default=None, description="Required: the confirmation the person saw. If it "
                                                                  "has been reverted or replaced since, the revert is "
                                                                  "refused (409 STALE_COPY); without it, 428.")


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
    engagement that bears on it. The shipped matrices are not changed. An
    entry someone else confirmed in the meantime is refused (409
    STALE_COPY): nothing is overwritten."""
    _engagement(db, engagement_id)
    for entry_id in payload.entries:
        active = (db.query(models.EngagementMatrixConfirmation)
                  .filter_by(engagement_id=engagement_id, entry_id=entry_id, reverted_at=None).one_or_none())
        if active is not None:
            raise error(409, f"Not saved: {entry_id} was confirmed by {active.decided_by} first (decision "
                             f"{active.decision_id}, {active.decided_on}). Nothing was overwritten. Reload to see it.",
                        code="STALE_COPY")
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
    if not payload.confirmation_id:
        raise error(428, f"Not saved: the revert does not say which confirmation of {payload.entry_id} it reverts. Send "
                         "the confirmation_id you saw, so a confirmation made or reverted since is not undone by "
                         "mistake.", field="confirmation_id", code="VERSION_REQUIRED")
    if payload.confirmation_id:
        active = (db.query(models.EngagementMatrixConfirmation)
                  .filter_by(engagement_id=engagement_id, entry_id=payload.entry_id, reverted_at=None)
                  .with_for_update().one_or_none())
        if active is None or str(active.id) != payload.confirmation_id:
            said = ("it has been reverted since" if active is None
                    else f"it was replaced since, by {active.decided_by}'s confirmation (decision {active.decision_id})")
            raise error(409, f"Not saved: the confirmation of {payload.entry_id} you saw is no longer the current one: "
                             f"{said}. Nothing was changed. Reload to see it.", code="STALE_COPY")
    try:
        engagement_matrix.revert(db, engagement_id, payload.entry_id, payload.by, payload.reason)
    except ValueError as exc:
        db.rollback()
        raise error(422, str(exc), code="NOT_CONFIRMED") from exc
    db.commit()
    return {"reverted": payload.entry_id}
