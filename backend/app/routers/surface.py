"""Read-only endpoints for the repository Surface section —
29-STEPS-004-005-INVENTORIES.md Part D. Nothing here mutates: step 4
(entry-point-inventory) and step 5 (outbound-invocation-inventory), both in
steps/step-003-fingerprinting/, own every row read.
"""

import uuid
from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.surface import capabilities
from app.surface.schemas import (
    EntryPointCapabilitiesOut,
    EntryPointInventoryOut,
    EntryPointOut,
    OutboundInventoryOut,
    OutboundInvocationOut,
    ProjectEntryPointsOut,
    ProjectOutboundOut,
)

router = APIRouter(prefix="/api", tags=["Surface"])

_REPOSITORY_NOT_FOUND = {"model": ErrorResponse, "description": "No repository exists with this id."}
_NOT_SCANNED = {
    "model": ErrorResponse,
    "description": "The entry-point inventory (lifecycle step 4) has not run yet for this repository.",
}


def _sort_key(row: models.EntryPoint) -> tuple:
    # The artifact's order: kind, then route or handler.
    http = row.detail if row.kind in ("http_controller_action", "http_minimal_api") else {}
    return (
        row.kind,
        http.get("routeTemplate") or http.get("mappedTemplate") or "",
        http.get("verb") or "",
        row.handler_type,
        row.handler_member or "",
        row.file_path,
        row.line_start,
        row.id,
    )


@router.get(
    "/repositories/{repository_id}/entry-points",
    response_model=EntryPointInventoryOut,
    summary="Get a repository's inbound surface: its entry points by project",
    response_description="Entry points grouped by project, in the artifact's order, with per-project and repository counts.",
    operation_id="get_repository_entry_points",
    responses={404: _REPOSITORY_NOT_FOUND, 409: _NOT_SCANNED},
)
def get_repository_entry_points(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    """What can call this repository's applications — HTTP routes, WCF and
    ASMX operations, gRPC and SignalR methods, WebForms pages, consumers,
    hosted services, scheduled jobs and mains. 409 until step 4 has run,
    so the UI can show an empty state naming the step."""
    repo = db.get(models.Repository, repository_id)
    if repo is None or repo.deleted_at is not None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")

    scan = db.get(models.EntryPointScan, repository_id)
    if scan is None:
        raise error(409, "The entry-point inventory has not run yet for this repository.", code="NOT_SCANNED")

    rows_by_project: dict[uuid.UUID, list[models.EntryPoint]] = {}
    for row in db.query(models.EntryPoint).filter(models.EntryPoint.repository_id == repository_id):
        rows_by_project.setdefault(row.project_id, []).append(row)

    projects = []
    for project in sorted(scan.project_summaries, key=lambda p: p["projectPath"]):
        project_id = uuid.UUID(project["projectId"])
        summary = project["summary"]
        rows = sorted(rows_by_project.get(project_id, []), key=_sort_key)
        projects.append(
            ProjectEntryPointsOut(
                project_id=project_id,
                project_path=project["projectPath"],
                status=project["status"],
                skip_reason=project.get("skipReason"),
                request_entry_point_count=sum(1 for r in rows if r.entry_class == "request"),
                lifecycle_hook_count=sum(1 for r in rows if r.entry_class == "lifecycle"),
                count_by_origin=dict(sorted(Counter(r.origin for r in rows).items())),
                count_by_kind=summary["countByKind"],
                count_by_verb=summary["countByVerb"],
                # Scans before 2.0.0 wrote unauthorisedCount.
                no_declared_authentication_count=summary.get("noDeclaredAuthenticationCount", summary.get("unauthorisedCount", 0)),
                authorisation_not_assessed_count=summary["authorisationNotAssessedCount"],
                global_authorisation=summary["globalAuthorisation"],
                conventional_routes=summary["conventionalRoutes"],
                entry_points=[
                    EntryPointOut(
                        id=r.id,
                        kind=r.kind,
                        origin=r.origin,
                        entry_class=r.entry_class,
                        handler_type=r.handler_type,
                        handler_member=r.handler_member,
                        file_path=r.file_path,
                        line_start=r.line_start,
                        line_end=r.line_end,
                        detail=r.detail,
                        confidence=float(r.confidence),
                        confidence_reasons=r.confidence_reasons,
                        auth_declared=r.auth_declared,
                    )
                    for r in rows
                ],
            )
        )

    totals = scan.summary
    return EntryPointInventoryOut(
        repository_id=repository_id,
        scanner_version=scan.scanner_version,
        skip_source=scan.skip_source,
        scanned_at=scan.scanned_at,
        entry_point_count=totals["entryPointCount"],
        request_entry_point_count=sum(p.request_entry_point_count for p in projects),
        lifecycle_hook_count=sum(p.lifecycle_hook_count for p in projects),
        count_by_origin=dict(sorted(Counter(e.origin for p in projects for e in p.entry_points).items())),
        count_by_kind=totals["countByKind"],
        count_by_verb=totals["countByVerb"],
        no_declared_authentication_count=totals.get("noDeclaredAuthenticationCount", totals.get("unauthorisedCount", 0)),
        authorisation_not_assessed_count=totals["authorisationNotAssessedCount"],
        auth_declared_scope=capabilities.AUTH_DECLARED_SCOPE,
        capabilities_manifest_version=(scan.capabilities or {}).get("manifestVersion"),
        capability_kinds=(scan.capabilities or {}).get("kinds", []),
        projects=projects,
    )


@router.get(
    "/workflow/steps/entry-point-inventory/capabilities",
    response_model=EntryPointCapabilitiesOut,
    summary="What entry-point kinds step 4 detects",
    response_description="The published capability manifest, with how often each kind is found across the estate.",
    operation_id="get_entry_point_capabilities",
    tags=["Workflow Steps"],
)
def get_entry_point_capabilities(db: Session = Depends(get_db)):
    """Step 4's capability manifest (steps/step-003-fingerprinting/schemas/
    entry-point-capabilities-*.json, highest version): every kind it looks
    for, and the patterns it does not. The same principle as extractor
    readiness — the platform declares what it can see, so finding none of a
    listed kind is a result, and a pattern under not_covered is a visible gap
    rather than a silent miss."""
    return capabilities.manifest_with_estate_counts(db)


_OUTBOUND_NOT_SCANNED = {
    "model": ErrorResponse,
    "description": "The outbound-invocation inventory (lifecycle step 5) has not run yet for this repository.",
}

_VERDICT_RANK = {"incompatible": 0, "requires_change": 1, "unknown": 2, "compatible": 3}

# What an outbound credential declaration means; the artifact carries the same note.
OUTBOUND_AUTH_DECLARED_SCOPE = (
    "authDeclared on an outbound invocation reports whether the client presents credentials, as declared in source and "
    "config. Credentials added outside the code (a sidecar, a gateway, a delegating handler registered elsewhere) are not "
    "visible to static analysis, so none_declared and not_assessed are prompts to review, not findings."
)


def _endpoint_display(row: models.OutboundInvocation) -> str:
    if row.resolution == "unresolved":
        return f"unresolved ({row.placeholder or 'dynamic'})"
    port = f":{row.endpoint_port}" if row.endpoint_port is not None else ""
    return f"{row.endpoint_scheme or '?'}://{row.endpoint_host or '?'}{port}{row.endpoint_path or ''}"


def _outbound_sort_key(row: models.OutboundInvocation) -> tuple:
    # The artifact's order: used before unused, incompatible first, then mechanism and endpoint.
    return (row.usage != "used", _VERDICT_RANK.get(row.linux_verdict, 9), row.mechanism, _endpoint_display(row), row.id)


@router.get(
    "/repositories/{repository_id}/outbound-invocations",
    response_model=OutboundInventoryOut,
    summary="Get a repository's outbound surface: what its applications call, by project",
    response_description="Invocations grouped by project, incompatible first, with per-project and repository counts.",
    operation_id="get_repository_outbound_invocations",
    responses={404: _REPOSITORY_NOT_FOUND, 409: _OUTBOUND_NOT_SCANNED},
)
def get_repository_outbound_invocations(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    """What this repository's applications call: SOAP and HTTP services,
    gRPC, databases, brokers, caches, secret stores, file shares, SMTP and
    LDAP, each with its normalised endpoint, environment bindings and
    Linux-compatibility verdict. 409 until step 5 has run, so the UI can
    show an empty state naming the step."""
    repo = db.get(models.Repository, repository_id)
    if repo is None or repo.deleted_at is not None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")

    scan = db.get(models.OutboundScan, repository_id)
    if scan is None:
        raise error(409, "The outbound-invocation inventory has not run yet for this repository.", code="NOT_SCANNED")

    rows_by_project: dict[uuid.UUID, list[models.OutboundInvocation]] = {}
    for row in db.query(models.OutboundInvocation).filter(models.OutboundInvocation.repository_id == repository_id):
        rows_by_project.setdefault(row.project_id, []).append(row)

    projects = []
    for project in sorted(scan.project_summaries, key=lambda p: p["projectPath"]):
        project_id = uuid.UUID(project["projectId"])
        rows = sorted(rows_by_project.get(project_id, []), key=_outbound_sort_key)
        projects.append(
            ProjectOutboundOut(
                project_id=project_id,
                project_path=project["projectPath"],
                status=project["status"],
                skip_reason=project.get("skipReason"),
                # Scans before 1.1.0 had no unused clients.
                unused_count=project["summary"].get("unusedCount", 0),
                count_by_mechanism=project["summary"]["countByMechanism"],
                count_by_verdict=project["summary"]["countByVerdict"],
                invocations=[
                    OutboundInvocationOut(
                        id=r.id,
                        mechanism=r.mechanism,
                        usage=r.usage,
                        endpoint_scheme=r.endpoint_scheme,
                        endpoint_host=r.endpoint_host,
                        endpoint_port=r.endpoint_port,
                        endpoint_path=r.endpoint_path,
                        resolution=r.resolution,
                        placeholder=r.placeholder,
                        detail=r.detail,
                        environment_bindings=r.environment_bindings,
                        call_sites=r.call_sites,
                        credentials=r.credentials,
                        auth_declared=r.auth_declared,
                        linux_verdict=r.linux_verdict,
                        linux_reasons=r.linux_reasons,
                        confidence=float(r.confidence),
                        confidence_reasons=r.confidence_reasons,
                    )
                    for r in rows
                ],
            )
        )

    totals = scan.summary
    return OutboundInventoryOut(
        repository_id=repository_id,
        scanner_version=scan.scanner_version,
        skip_source=scan.skip_source,
        scanned_at=scan.scanned_at,
        invocation_count=totals["invocationCount"],
        unused_count=totals.get("unusedCount", 0),
        count_by_mechanism=totals["countByMechanism"],
        count_by_verdict=totals["countByVerdict"],
        auth_declared_scope=OUTBOUND_AUTH_DECLARED_SCOPE,
        projects=projects,
    )
