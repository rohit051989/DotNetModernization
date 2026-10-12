"""Read-only endpoints for the repository Surface section —
29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md Part D. Nothing here mutates: step 4
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
from app.estate.analysis import production_binding
from app.estate import engagement_matrix, soap_compatibility, wcf_matrix
from app.routers import estate as estate_router
from app.surface.schemas import RepositorySoapOut
from app.surface.schemas import (
    ApplicationBackendOut,
    BackendCallOut,
    BackendEndpointOut,
    BackendHostOut,
    EntryPointBackendOut,
    EntryPointBackendRowOut,
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

    # Step 11's origin reconciliations (31-DEPENDENCY-AND-CONTEXT-MAP Part E4), applied as an
    # overlay: step 4 owns its rows and its next rescan would revert an edit.
    reconciled = {
        r.entry_point_id: r
        for r in db.query(models.OriginReconciliation).filter(
            models.OriginReconciliation.engagement_id == repo.engagement_id,
            models.OriginReconciliation.entry_point_id.in_([row.id for rows in rows_by_project.values() for row in rows]),
        )
    }

    def origin(row: models.EntryPoint) -> str:
        return reconciled[row.id].reconciled_origin if row.id in reconciled else row.origin

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
                count_by_origin=dict(sorted(Counter(origin(r) for r in rows).items())),
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
                        origin=origin(r),
                        origin_reconciled_from=r.origin if r.id in reconciled else None,
                        origin_reconciliation_reason=reconciled[r.id].reason if r.id in reconciled else None,
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
                        construction_sites=r.construction_sites or [],
                        credentials=r.credentials,
                        auth_declared=r.auth_declared,
                        linux_verdict=r.linux_verdict,
                        linux_reasons=r.linux_reasons,
                        confidence=float(r.confidence),
                        confidence_reasons=r.confidence_reasons,
                    )
                    for r in rows
                ],
                deploy_parameters=project.get("deployParameters") or [],
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


# ---------- inbound operations -> backend calls (step 5 1.3.0) ----------


def _service_and_operation(row: models.EntryPoint) -> tuple[str, str]:
    detail = row.detail or {}
    if row.kind == "wcf_operation":
        return detail.get("contract") or row.handler_type, detail.get("operation") or row.handler_member or ""
    if row.kind == "asmx_web_method":
        return detail.get("servicePath") or row.handler_type, detail.get("method") or row.handler_member or ""
    if row.kind == "grpc_service_method":
        return detail.get("service") or row.handler_type, detail.get("method") or row.handler_member or ""
    if row.kind in ("http_controller_action", "http_minimal_api", "razor_page"):
        route = detail.get("mappedTemplate") or detail.get("routeTemplate") or "(conventional route)"
        return row.handler_type, f"{detail.get('verb') or 'ANY'} /{route.lstrip('/')}"
    return row.handler_type, row.handler_member or row.kind


def _host_out(binding: dict) -> BackendHostOut:
    return BackendHostOut(
        environment=binding.get("environment") or "default", host=binding.get("host"), port=binding.get("port"),
        path=binding.get("path"), source_file=binding.get("sourceFile"), deploy_parameter=binding.get("deployParameter"),
        host_project=binding.get("hostProject"), linux_verdict=binding.get("linuxVerdict"),
    )


def _endpoint(invocation: models.OutboundInvocation, production_environment: str | None) -> BackendEndpointOut:
    """The production environment's binding where the call has one (the
    same rule as the estate register, 31-DEPENDENCY-AND-CONTEXT-MAP Part C1), with every
    other environment beneath."""
    bindings = invocation.environment_bindings or []
    production = production_binding({"environment_bindings": bindings}, production_environment)
    if production is not None:
        return BackendEndpointOut(shown=_host_out(production), grouped_by="production_environment",
                                  others=[_host_out(b) for b in bindings if b is not production])
    shown = BackendHostOut(environment="as found", host=invocation.endpoint_host, port=invocation.endpoint_port,
                           path=invocation.endpoint_path, source_file=None, deploy_parameter=None, host_project=None,
                           linux_verdict=invocation.linux_verdict)
    return BackendEndpointOut(shown=shown, grouped_by="host", others=[_host_out(b) for b in bindings])


@router.get(
    "/repositories/{repository_id}/entry-point-backend",
    response_model=EntryPointBackendOut,
    summary="Get which backend calls each inbound operation reaches, per application",
    response_description="Every request entry point by project, with the outbound calls it reaches.",
    operation_id="get_repository_entry_point_backend",
    responses={404: _REPOSITORY_NOT_FOUND, 409: _OUTBOUND_NOT_SCANNED},
)
def get_repository_entry_point_backend(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    """Per application, every inbound operation (step 4's request entry
    points) and the backend calls it reaches (step 5 1.3.0): directly in the
    entry point's method, or through methods of the same class, with depth
    and whether each call is conditional or in a loop. Operations that call
    nothing are listed too. The endpoint shows the production environment's
    host where the engagement sets one and the call has a binding for it."""
    repo = db.get(models.Repository, repository_id)
    if repo is None or repo.deleted_at is not None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")
    if db.get(models.OutboundScan, repository_id) is None:
        raise error(409, "The outbound-invocation inventory has not run yet for this repository.", code="NOT_SCANNED")

    engagement = db.get(models.Engagement, repo.engagement_id)
    production_environment = engagement.production_environment if engagement else None
    reach = {r.entry_point_id: r for r in db.query(models.EntryPointBackend).filter(models.EntryPointBackend.repository_id == repository_id)}
    invocations = {i.id: i for i in db.query(models.OutboundInvocation).filter(models.OutboundInvocation.repository_id == repository_id)}
    projects = {p.id: p.relative_path for p in db.query(models.Project).filter(models.Project.repository_id == repository_id)}

    by_project: dict[uuid.UUID, list[models.EntryPoint]] = {}
    for row in db.query(models.EntryPoint).filter(models.EntryPoint.repository_id == repository_id, models.EntryPoint.entry_class == "request"):
        by_project.setdefault(row.project_id, []).append(row)

    applications = []
    for project_id in sorted(by_project, key=lambda pid: projects.get(pid, "")):
        rows = sorted(by_project[project_id], key=lambda r: (*_service_and_operation(r), r.id))
        out = []
        for number, row in enumerate(rows, start=1):
            service, operation = _service_and_operation(row)
            found = reach.get(row.id)
            calls = []
            for call in (found.calls if found else []):
                invocation = invocations.get(call["invocationId"])
                if invocation is None:
                    continue
                block = (invocation.detail or {}).get("block") or {}
                calls.append(BackendCallOut(
                    invocation_id=invocation.id, mechanism=call["mechanism"], contract=block.get("contract"),
                    operation=call.get("operation"), call_site=call["callSite"], depth=call["depth"], via=call.get("via") or [],
                    conditional=call["conditional"], in_loop=call["inLoop"], context=call.get("context") or [],
                    endpoint=_endpoint(invocation, production_environment), linux_verdict=invocation.linux_verdict,
                ))
            out.append(EntryPointBackendRowOut(
                number=number, entry_point_id=row.id, kind=row.kind, service=service, operation=operation,
                handler={"type": row.handler_type, "member": row.handler_member, "filePath": row.file_path, "lineStart": row.line_start},
                status=found.status if found else "not_assessed", calls=calls, unresolved=found.unresolved if found else [],
            ))
        applications.append(ApplicationBackendOut(project_id=project_id, project_path=projects.get(project_id, ""), rows=out))

    return EntryPointBackendOut(repository_id=repository_id, production_environment=production_environment, applications=applications)


@router.get(
    "/repositories/{repository_id}/soap-compatibility",
    response_model=RepositorySoapOut,
    summary="Get a repository's SOAP calls with both verdicts per environment",
    response_description="Each used SOAP client, per environment: runtime and platform verdicts with their matrix entries' "
                         "live confirmation, and the call's row in the estate report.",
    operation_id="get_repository_soap_compatibility",
    responses={404: _REPOSITORY_NOT_FOUND, 409: _OUTBOUND_NOT_SCANNED},
)
def get_repository_soap_compatibility(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    """The repository's own view of the SOAP backend compatibility report
    (31-DEPENDENCY-AND-CONTEXT-MAP.md Part J). Read from this repository's
    outbound invocations, so a rescan updates it at once; the matrix entries'
    confirmation, probes and contradictions are read live, as the report reads
    them. The estate report is built by the estate consolidation: when it has
    not run since this repository's last scan, estate_stale says so, and a
    call's link to its row there may point at what the scan replaced."""
    repo = db.get(models.Repository, repository_id)
    if repo is None or repo.deleted_at is not None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")
    scan = db.get(models.OutboundScan, repository_id)
    if scan is None:
        raise error(409, "The outbound-invocation inventory has not run yet for this repository.", code="NOT_SCANNED")
    engagement = db.get(models.Engagement, repo.engagement_id)

    run, artifacts = estate_router._latest_run(db, engagement.id)
    report = artifacts.get("soap-backend-compatibility") or {}
    rows_in_report = {caller["invocationId"]: host["host"] for host in report.get("hosts", []) for caller in host["callers"]}
    estate_run_at = run.ended_at if run is not None else None
    stale = estate_run_at is None or (scan.scanned_at is not None and scan.scanned_at > estate_run_at)
    note = None
    if estate_run_at is None:
        note = "The estate consolidation has never run for this engagement: there is no estate report to link to."
    elif stale:
        note = (f"The estate report was built {estate_run_at:%Y-%m-%d %H:%M} UTC, before this repository's last scan "
                f"({scan.scanned_at:%Y-%m-%d %H:%M} UTC). The verdicts here are the scan's; the estate report has not been "
                f"rerun since, so its totals and rows do not include this scan yet. Rerun the estate consolidation.")

    target_wcf = engagement.target_wcf_client_version or wcf_matrix.target_wcf_client(
        wcf_matrix.load("support"), engagement.target_framework)
    applied = engagement_matrix.overlay(db, engagement.id)
    live = {kind: engagement_matrix.apply(kind, wcf_matrix.entries(kind), applied) for kind in wcf_matrix.KINDS}
    soap = db.query(models.OutboundInvocation).filter(models.OutboundInvocation.repository_id == repository_id,
                                                      models.OutboundInvocation.mechanism == "soap_client")
    projects = {p["projectId"]: p["projectPath"] for p in scan.project_summaries}
    calls, unused = [], 0
    for row in sorted(soap, key=lambda r: (projects.get(str(r.project_id), ""), r.id)):
        if row.usage != "used":
            unused += 1
            continue
        block = (row.detail or {}).get("block") or {}
        environments = []
        for b in sorted(row.environment_bindings or [], key=lambda b: (b.get("environment") or "", b.get("sourceFile") or "")):
            security = b.get("soap") or {"binding": block.get("binding"), "securityMode": block.get("securityMode"),
                                         "clientCredentialType": block.get("clientCredentialType"),
                                         "securitySource": block.get("securitySource")}
            environments.append({
                "environment": b.get("environment") or "default",
                "address": soap_compatibility._address(b),
                "sourceFile": b.get("sourceFile"),
                "binding": security.get("binding"),
                "securityMode": security.get("securityMode"),
                "credentialType": "None" if security.get("securityMode") == "None" else security.get("clientCredentialType"),
                "securitySource": security.get("securitySource"),
                "runtime": wcf_matrix.live_verdict("support", b.get("runtimeVerdict") or "not_assessed", b.get("runtimeMatrixEntry"),
                                                   target_wcf, live["support"]),
                "platform": wcf_matrix.live_verdict("platform", b.get("linuxVerdict") or row.linux_verdict, b.get("platformMatrixEntry"),
                                                    target_wcf, live["platform"]),
            })
        calls.append({
            "invocationId": row.id, "projectPath": projects.get(str(row.project_id), ""),
            "contract": block.get("contract"), "clientType": block.get("clientType"), "endpoint": _endpoint_display(row),
            "environments": environments, "estateHost": rows_in_report.get(row.id),
        })
    return RepositorySoapOut(repository_id=repository_id, engagement_id=engagement.id, scanned_at=scan.scanned_at,
                             estate_run_at=estate_run_at, estate_stale=stale, estate_note=note,
                             target_wcf_client_version=target_wcf, unused_count=unused, calls=calls)
