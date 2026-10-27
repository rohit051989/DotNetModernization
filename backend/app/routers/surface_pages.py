"""The repository Surface section a page at a time (app.results.paging): each panel's summary, its projects, and each
project's entry points, invocations or operations, served by the database 20 at a time with the filter box's text.
The whole-repository endpoints (app.routers.surface) stay for tools; the UI reads these. Read-only.
"""
import datetime
import uuid
from collections import Counter

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.estate import engagement_matrix, soap_compatibility, wcf_matrix
from app.results import store
from app.results.paging import PageOut, PageParams, page
from app.routers import surface
from app.surface import capabilities
from app.surface.schemas import (
    BackendCallOut,
    EntryPointBackendRowOut,
    EntryPointOut,
    OutboundInvocationOut,
)

router = APIRouter(prefix="/api", tags=["Surface"])

_RESPONSES = {404: {"model": ErrorResponse, "description": "No repository exists with this id."},
              409: {"model": ErrorResponse, "description": "The step behind this panel has not run yet."}}


def _repository(db: Session, repository_id: uuid.UUID) -> models.Repository:
    repo = db.get(models.Repository, repository_id)
    if repo is None or repo.deleted_at is not None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")
    return repo


def _entry_scan(db: Session, repository_id: uuid.UUID) -> models.EntryPointScan:
    scan = db.get(models.EntryPointScan, repository_id)
    if scan is None:
        raise error(409, "The entry-point inventory has not run yet for this repository.", code="NOT_SCANNED")
    return scan


def _outbound_scan(db: Session, repository_id: uuid.UUID) -> models.OutboundScan:
    scan = db.get(models.OutboundScan, repository_id)
    if scan is None:
        raise error(409, "The outbound-invocation inventory has not run yet for this repository.", code="NOT_SCANNED")
    return scan


def _reconciled(db: Session, engagement_id: str, ids) -> dict:
    """Step 11's origin reconciliations of these entry points (an overlay: step 4's rows are never rewritten)."""
    ids = list(ids)
    if not ids:
        return {}
    return {r.entry_point_id: r for r in db.query(models.OriginReconciliation).filter(
        models.OriginReconciliation.engagement_id == engagement_id, models.OriginReconciliation.entry_point_id.in_(ids))}


# ---------------------------------------------------------------- inbound

class EntryPointSummaryOut(BaseModel):
    repository_id: uuid.UUID
    scanner_version: str
    skip_source: str
    scanned_at: datetime.datetime | None
    entry_point_count: int
    request_entry_point_count: int
    lifecycle_hook_count: int
    count_by_kind: dict[str, int]
    count_by_origin: dict[str, int]
    count_by_verb: dict[str, int]
    no_declared_authentication_count: int
    authorisation_not_assessed_count: int
    auth_declared_scope: str
    capabilities_manifest_version: str | None
    capability_kinds: list[str]
    project_count: int
    projects_with_requests: int
    lifecycle_hooks_without_requests: int = Field(description="Lifecycle hooks of the projects with no request entry point.")


@router.get("/repositories/{repository_id}/entry-points/summary", response_model=EntryPointSummaryOut,
            summary="Get a repository's inbound surface totals, without its lists", operation_id="get_entry_point_summary",
            responses=_RESPONSES)
def get_entry_point_summary(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    repo = _repository(db, repository_id)
    scan = _entry_scan(db, repository_id)
    counts = db.execute(text("""
        select e.project_id, count(*) filter (where entry_class = 'request') as requests,
               count(*) filter (where entry_class = 'lifecycle') as lifecycle
        from entry_points e where e.repository_id = :r group by e.project_id
    """), {"r": repository_id}).all()
    by_project = {c.project_id: c for c in counts}
    origins = db.execute(text("""
        select coalesce(o.reconciled_origin, e.origin) as origin, count(*) as n
        from entry_points e
        left join origin_reconciliations o on o.entry_point_id = e.id and o.engagement_id = :e
        where e.repository_id = :r group by 1
    """), {"r": repository_id, "e": repo.engagement_id}).all()
    project_ids = [uuid.UUID(p["projectId"]) for p in scan.project_summaries]
    with_requests = [pid for pid in project_ids if by_project.get(pid) and by_project[pid].requests > 0]
    totals = scan.summary
    return EntryPointSummaryOut(
        repository_id=repository_id, scanner_version=scan.scanner_version, skip_source=scan.skip_source,
        scanned_at=scan.scanned_at, entry_point_count=totals["entryPointCount"],
        request_entry_point_count=sum(c.requests for c in counts), lifecycle_hook_count=sum(c.lifecycle for c in counts),
        count_by_kind=totals["countByKind"], count_by_origin=dict(sorted((o.origin, o.n) for o in origins)),
        count_by_verb=totals["countByVerb"],
        no_declared_authentication_count=totals.get("noDeclaredAuthenticationCount", totals.get("unauthorisedCount", 0)),
        authorisation_not_assessed_count=totals["authorisationNotAssessedCount"],
        auth_declared_scope=capabilities.AUTH_DECLARED_SCOPE,
        capabilities_manifest_version=(scan.capabilities or {}).get("manifestVersion"),
        capability_kinds=(scan.capabilities or {}).get("kinds", []),
        project_count=len(project_ids), projects_with_requests=len(with_requests),
        lifecycle_hooks_without_requests=sum(by_project[pid].lifecycle for pid in project_ids
                                             if by_project.get(pid) and by_project[pid].requests == 0))


_ENTRY_PROJECTS = """
    select ps as summary, lower(ps->>'projectPath') as search, ps->>'projectPath' as k_path,
           coalesce(c.requests, 0) as requests
    from entry_point_scans s cross join lateral jsonb_array_elements(s.project_summaries) ps
    left join lateral (
        select count(*) filter (where e.entry_class = 'request') as requests
        from entry_points e where e.repository_id = s.repository_id and e.project_id = (ps->>'projectId')::uuid
    ) c on true
    where s.repository_id = :r
"""


@router.get("/repositories/{repository_id}/entry-points/projects", response_model=PageOut,
            summary="Get a page of a repository's projects with their entry-point counts",
            operation_id="list_entry_point_projects", responses=_RESPONSES)
def list_entry_point_projects(repository_id: uuid.UUID,
                              with_requests: bool = Query(True, description="Projects with request entry points; false: "
                                                                            "those with none (the grouped line)."),
                              paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as the inventory's projects, without their entry points: counts, authorisation and routes, and `kinds`
    ({entry_class, kind, count}) for the groups the entry points are listed in. By path; the filter matches it."""
    repo = _repository(db, repository_id)
    _entry_scan(db, repository_id)
    source = f"select summary as item, search, k_path, requests from ({_ENTRY_PROJECTS}) x"
    result = page(db, source, {"r": repository_id}, paging, order="k_path",
                  where="requests > 0" if with_requests else "requests = 0")
    ids = [uuid.UUID(p["projectId"]) for p in result.items]
    rows = db.query(models.EntryPoint).filter(models.EntryPoint.repository_id == repository_id,
                                              models.EntryPoint.project_id.in_(ids)).all() if ids else []
    reconciled = _reconciled(db, repo.engagement_id, (r.id for r in rows))
    by_project: dict[uuid.UUID, list[models.EntryPoint]] = {}
    for row in rows:
        by_project.setdefault(row.project_id, []).append(row)
    items = []
    for project in result.items:
        pid = uuid.UUID(project["projectId"])
        mine = by_project.get(pid, [])
        summary = project["summary"]
        kinds = Counter((r.entry_class, r.kind) for r in mine)
        items.append({
            "project_id": str(pid), "project_path": project["projectPath"], "status": project["status"],
            "skip_reason": project.get("skipReason"),
            "request_entry_point_count": sum(1 for r in mine if r.entry_class == "request"),
            "lifecycle_hook_count": sum(1 for r in mine if r.entry_class == "lifecycle"),
            "count_by_origin": dict(sorted(Counter(reconciled[r.id].reconciled_origin if r.id in reconciled else r.origin
                                                   for r in mine).items())),
            "count_by_kind": summary["countByKind"], "count_by_verb": summary["countByVerb"],
            "no_declared_authentication_count": summary.get("noDeclaredAuthenticationCount", summary.get("unauthorisedCount", 0)),
            "authorisation_not_assessed_count": summary["authorisationNotAssessedCount"],
            "global_authorisation": summary["globalAuthorisation"], "conventional_routes": summary["conventionalRoutes"],
            "kinds": [{"entry_class": c, "kind": k, "count": n} for (c, k), n in sorted(kinds.items())],
        })
    return PageOut(total=result.total, matching=result.matching, offset=result.offset, items=items)


# The artifact's order (app.routers.surface._sort_key): kind, then route or handler.
_ENTRY_ORDER = """kind, coalesce(case when kind in ('http_controller_action', 'http_minimal_api')
                                      then coalesce(nullif(detail->>'routeTemplate', ''), nullif(detail->>'mappedTemplate', '')) end, '') collate "C",
                 coalesce(case when kind in ('http_controller_action', 'http_minimal_api') then detail->>'verb' end, '') collate "C",
                 handler_type collate "C", coalesce(handler_member, '') collate "C", file_path collate "C", line_start, id"""


@router.get("/repositories/{repository_id}/entry-points/list", response_model=PageOut,
            summary="Get a page of one project's entry points of one kind", operation_id="list_entry_points",
            responses=_RESPONSES)
def list_entry_points(repository_id: uuid.UUID, project_id: uuid.UUID = Query(...), entry_class: str = Query(...),
                      kind: str = Query(...), paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as EntryPointOut, in the artifact's order. The filter matches the handler, the verb and route, and what
    the kind's detail says."""
    repo = _repository(db, repository_id)
    _entry_scan(db, repository_id)
    source = f"""
        select jsonb_build_object('id', id) as item, kind, detail, handler_type, handler_member, file_path, line_start, id,
               lower(concat_ws(' ', handler_type || coalesce('.' || handler_member, ''), detail->>'verb',
                               detail->>'routeTemplate', detail::text)) as search
        from entry_points where repository_id = :r and project_id = :p and entry_class = :c and kind = :k
    """
    result = page(db, source, {"r": repository_id, "p": project_id, "c": entry_class, "k": kind}, paging, order=_ENTRY_ORDER)
    ids = [i["id"] for i in result.items]
    rows = {r.id: r for r in db.query(models.EntryPoint).filter(models.EntryPoint.id.in_(ids))} if ids else {}
    reconciled = _reconciled(db, repo.engagement_id, ids)
    items = []
    for entry_id in ids:
        r = rows[entry_id]
        items.append(EntryPointOut(
            id=r.id, kind=r.kind, origin=reconciled[r.id].reconciled_origin if r.id in reconciled else r.origin,
            origin_reconciled_from=r.origin if r.id in reconciled else None,
            origin_reconciliation_reason=reconciled[r.id].reason if r.id in reconciled else None,
            entry_class=r.entry_class, handler_type=r.handler_type, handler_member=r.handler_member, file_path=r.file_path,
            line_start=r.line_start, line_end=r.line_end, detail=r.detail, confidence=float(r.confidence),
            confidence_reasons=r.confidence_reasons, auth_declared=r.auth_declared).model_dump(mode="json"))
    return PageOut(total=result.total, matching=result.matching, offset=result.offset, items=items)


# ---------------------------------------------------------------- outbound

class OutboundSummaryOut(BaseModel):
    repository_id: uuid.UUID
    scanner_version: str
    skip_source: str
    scanned_at: datetime.datetime | None
    invocation_count: int
    unused_count: int
    count_by_mechanism: dict[str, int]
    count_by_verdict: dict[str, int]
    auth_declared_scope: str
    project_count: int
    projects_with_invocations: int


@router.get("/repositories/{repository_id}/outbound-invocations/summary", response_model=OutboundSummaryOut,
            summary="Get a repository's outbound surface totals, without its lists",
            operation_id="get_outbound_summary", responses=_RESPONSES)
def get_outbound_summary(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    _repository(db, repository_id)
    scan = _outbound_scan(db, repository_id)
    with_invocations = db.execute(text("""
        select count(distinct project_id) from outbound_invocations where repository_id = :r
    """), {"r": repository_id}).scalar()
    totals = scan.summary
    return OutboundSummaryOut(
        repository_id=repository_id, scanner_version=scan.scanner_version, skip_source=scan.skip_source,
        scanned_at=scan.scanned_at, invocation_count=totals["invocationCount"], unused_count=totals.get("unusedCount", 0),
        count_by_mechanism=totals["countByMechanism"], count_by_verdict=totals["countByVerdict"],
        auth_declared_scope=surface.OUTBOUND_AUTH_DECLARED_SCOPE, project_count=len(scan.project_summaries),
        projects_with_invocations=with_invocations)


# Used before unused, incompatible first (app.routers.surface._outbound_sort_key).
_VERDICT_RANK = """case when usage <> 'used' then 9 else case linux_verdict when 'incompatible' then 0
                   when 'requires_change' then 1 when 'unknown' then 2 when 'compatible' then 3 else 9 end end"""
def _endpoint(o: str = "") -> str:
    """The endpoint as shown (app.routers.surface._endpoint_display), in SQL; `o` the table's alias with its dot."""
    return (f"case when {o}resolution = 'unresolved' then 'unresolved (' || coalesce({o}placeholder, 'dynamic') || ')' "
            f"else coalesce({o}endpoint_scheme, '?') || '://' || coalesce({o}endpoint_host, '?') "
            f"|| coalesce(':' || {o}endpoint_port, '') || coalesce({o}endpoint_path, '') end")


@router.get("/repositories/{repository_id}/outbound-invocations/projects", response_model=PageOut,
            summary="Get a page of a repository's projects with their outbound counts",
            operation_id="list_outbound_projects", responses=_RESPONSES)
def list_outbound_projects(repository_id: uuid.UUID,
                           with_invocations: bool = Query(True, description="Projects with invocations; false: those "
                                                                            "with none (the grouped line)."),
                           paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as the inventory's projects, without their invocations: counts, deploy parameters, `invocation_count`
    and `mechanisms` ({mechanism, count, worst_rank}). The most incompatible first, then by path; the filter matches
    the path."""
    _repository(db, repository_id)
    _outbound_scan(db, repository_id)
    source = f"""
        select ps as item, lower(ps->>'projectPath') as search, ps->>'projectPath' as k_path,
               coalesce(c.n, 0) as invocations, coalesce(c.rank, 9) as rank
        from outbound_scans s cross join lateral jsonb_array_elements(s.project_summaries) ps
        left join lateral (
            select count(*) as n, min({_VERDICT_RANK}) as rank
            from outbound_invocations o where o.repository_id = s.repository_id and o.project_id = (ps->>'projectId')::uuid
        ) c on true
        where s.repository_id = :r
    """
    result = page(db, source, {"r": repository_id}, paging, order="rank, k_path",
                  where="invocations > 0" if with_invocations else "invocations = 0")
    ids = [uuid.UUID(p["projectId"]) for p in result.items]
    groups = db.execute(text(f"""
        select project_id, mechanism, count(*) as n, min({_VERDICT_RANK}) as worst
        from outbound_invocations where repository_id = :r and project_id = any(:ids) group by project_id, mechanism
    """), {"r": repository_id, "ids": ids}).all() if ids else []
    by_project: dict[uuid.UUID, list] = {}
    for g in groups:
        by_project.setdefault(g.project_id, []).append({"mechanism": g.mechanism, "count": g.n, "worst_rank": g.worst})
    items = []
    for project in result.items:
        pid = uuid.UUID(project["projectId"])
        mechanisms = by_project.get(pid, [])
        items.append({
            "project_id": str(pid), "project_path": project["projectPath"], "status": project["status"],
            "skip_reason": project.get("skipReason"), "unused_count": project["summary"].get("unusedCount", 0),
            "count_by_mechanism": project["summary"]["countByMechanism"], "count_by_verdict": project["summary"]["countByVerdict"],
            "deploy_parameters": project.get("deployParameters") or [],
            "invocation_count": sum(m["count"] for m in mechanisms), "mechanisms": mechanisms,
        })
    return PageOut(total=result.total, matching=result.matching, offset=result.offset, items=items)


@router.get("/repositories/{repository_id}/outbound-invocations/list", response_model=PageOut,
            summary="Get a page of one project's invocations of one mechanism", operation_id="list_outbound_invocations",
            responses=_RESPONSES)
def list_outbound_invocations(repository_id: uuid.UUID, project_id: uuid.UUID = Query(...), mechanism: str = Query(...),
                              paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as OutboundInvocationOut: used before unused, incompatible first, then by endpoint. The filter matches
    the endpoint and what the mechanism's block says."""
    _repository(db, repository_id)
    _outbound_scan(db, repository_id)
    source = f"""
        select jsonb_build_object('id', id) as item, {_VERDICT_RANK} as rank, {_endpoint()} as k_endpoint, id,
               lower(concat_ws(' ', {_endpoint()}, detail::text)) as search
        from outbound_invocations where repository_id = :r and project_id = :p and mechanism = :m
    """
    result = page(db, source, {"r": repository_id, "p": project_id, "m": mechanism}, paging,
                  order='rank, k_endpoint collate "C", id')
    ids = [i["id"] for i in result.items]
    rows = {r.id: r for r in db.query(models.OutboundInvocation).filter(models.OutboundInvocation.id.in_(ids))} if ids else {}
    items = [OutboundInvocationOut(
        id=r.id, mechanism=r.mechanism, usage=r.usage, endpoint_scheme=r.endpoint_scheme, endpoint_host=r.endpoint_host,
        endpoint_port=r.endpoint_port, endpoint_path=r.endpoint_path, resolution=r.resolution, placeholder=r.placeholder,
        detail=r.detail, environment_bindings=r.environment_bindings, call_sites=r.call_sites,
        construction_sites=r.construction_sites or [], credentials=r.credentials, auth_declared=r.auth_declared,
        linux_verdict=r.linux_verdict, linux_reasons=r.linux_reasons, confidence=float(r.confidence),
        confidence_reasons=r.confidence_reasons).model_dump(mode="json") for r in (rows[i] for i in ids)]
    return PageOut(total=result.total, matching=result.matching, offset=result.offset, items=items)


# ---------------------------------------------------------------- inbound operations -> backend calls

# app.routers.surface._service_and_operation, in SQL.
_SERVICE = """case kind when 'wcf_operation' then coalesce(nullif(detail->>'contract', ''), handler_type)
                        when 'asmx_web_method' then coalesce(nullif(detail->>'servicePath', ''), handler_type)
                        when 'grpc_service_method' then coalesce(nullif(detail->>'service', ''), handler_type)
                        else handler_type end"""
_OPERATION = """case when kind = 'wcf_operation' then coalesce(nullif(detail->>'operation', ''), nullif(handler_member, ''), '')
                     when kind in ('asmx_web_method', 'grpc_service_method')
                          then coalesce(nullif(detail->>'method', ''), nullif(handler_member, ''), '')
                     when kind in ('http_controller_action', 'http_minimal_api', 'razor_page')
                          then coalesce(nullif(detail->>'verb', ''), 'ANY') || ' /' || ltrim(coalesce(nullif(detail->>'mappedTemplate', ''),
                               nullif(detail->>'routeTemplate', ''), '(conventional route)'), '/')
                     else coalesce(nullif(handler_member, ''), kind) end"""


class BackendSummaryOut(BaseModel):
    repository_id: uuid.UUID
    production_environment: str | None
    operations: int
    applications: int = Field(description="Projects with at least one inbound (request) operation.")
    count_by_status: dict[str, int]


def _backend_ready(db: Session, repository_id: uuid.UUID) -> models.Repository:
    repo = _repository(db, repository_id)
    _outbound_scan(db, repository_id)
    return repo


# One row per application (a project with request entry points) and status.
_BACKEND_STATUSES = """
    select e.project_id, coalesce(p.relative_path, '') as project_path, coalesce(b.status, 'not_assessed') as status,
           count(*) as k
    from entry_points e
    left join entry_point_backend b on b.entry_point_id = e.id and b.repository_id = e.repository_id
    left join projects p on p.id = e.project_id
    where e.repository_id = :r and e.entry_class = 'request'
    group by 1, 2, 3
"""


@router.get("/repositories/{repository_id}/entry-point-backend/summary", response_model=BackendSummaryOut,
            summary="Get the totals of which backend calls each inbound operation reaches",
            operation_id="get_entry_point_backend_summary", responses=_RESPONSES)
def get_entry_point_backend_summary(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    repo = _backend_ready(db, repository_id)
    engagement = db.get(models.Engagement, repo.engagement_id)
    rows = db.execute(text(_BACKEND_STATUSES), {"r": repository_id}).all()
    statuses = Counter()
    for row in rows:
        statuses[row.status] += row.k
    return BackendSummaryOut(repository_id=repository_id,
                             production_environment=engagement.production_environment if engagement else None,
                             operations=sum(statuses.values()), applications=len({r.project_id for r in rows}),
                             count_by_status=dict(sorted(statuses.items())))


@router.get("/repositories/{repository_id}/entry-point-backend/applications", response_model=PageOut,
            summary="Get a page of a repository's applications with their backend-reach counts",
            operation_id="list_entry_point_backend_applications", responses=_RESPONSES)
def list_entry_point_backend_applications(repository_id: uuid.UUID, paging: PageParams = Depends(),
                                          db: Session = Depends(get_db)):
    """Items: project_id, project_path, operations and counts ({yes, no, unresolved, not_assessed}). By path; the
    filter matches it."""
    _backend_ready(db, repository_id)
    source = f"""
        select jsonb_build_object('project_id', project_id, 'project_path', project_path, 'operations', sum(k),
                                  'counts', jsonb_object_agg(status, k)) as item,
               lower(project_path) as search, project_path as k_path
        from ({_BACKEND_STATUSES}) s group by project_id, project_path
    """
    return page(db, source, {"r": repository_id}, paging, order='k_path collate "C"')


@router.get("/repositories/{repository_id}/entry-point-backend/operations", response_model=PageOut,
            summary="Get a page of one application's inbound operations with the backend calls each reaches",
            operation_id="list_entry_point_backend_operations", responses=_RESPONSES)
def list_entry_point_backend_operations(repository_id: uuid.UUID, project_id: uuid.UUID = Query(...),
                                        paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as EntryPointBackendRowOut, numbered by service and operation. The filter matches the service, the
    operation and the handler."""
    repo = _backend_ready(db, repository_id)
    source = f"""
        select jsonb_build_object('id', id, 'number', number, 'service', service, 'operation', operation) as item,
               number, lower(concat_ws(' ', service, operation, handler_type, handler_member)) as search
        from (
            select id, handler_type, handler_member, {_SERVICE} as service, {_OPERATION} as operation,
                   row_number() over (order by {_SERVICE} collate "C", {_OPERATION} collate "C", id collate "C") as number
            from entry_points where repository_id = :r and project_id = :p and entry_class = 'request'
        ) x
    """
    result = page(db, source, {"r": repository_id, "p": project_id}, paging, order="number")
    ids = [i["id"] for i in result.items]
    if not ids:
        return result
    engagement = db.get(models.Engagement, repo.engagement_id)
    production_environment = engagement.production_environment if engagement else None
    rows = {r.id: r for r in db.query(models.EntryPoint).filter(models.EntryPoint.id.in_(ids))}
    reach = {r.entry_point_id: r for r in db.query(models.EntryPointBackend).filter(
        models.EntryPointBackend.repository_id == repository_id, models.EntryPointBackend.entry_point_id.in_(ids))}
    invocation_ids = {call["invocationId"] for r in reach.values() for call in (r.calls or [])}
    invocations = {i.id: i for i in db.query(models.OutboundInvocation).filter(
        models.OutboundInvocation.id.in_(invocation_ids))} if invocation_ids else {}
    items = []
    for shown in result.items:
        row = rows[shown["id"]]
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
                endpoint=surface._endpoint(invocation, production_environment), linux_verdict=invocation.linux_verdict))
        items.append(EntryPointBackendRowOut(
            number=shown["number"], entry_point_id=row.id, kind=row.kind, service=shown["service"],
            operation=shown["operation"],
            handler={"type": row.handler_type, "member": row.handler_member, "filePath": row.file_path,
                     "lineStart": row.line_start},
            status=found.status if found else "not_assessed", calls=calls,
            unresolved=found.unresolved if found else []).model_dump(mode="json"))
    return PageOut(total=result.total, matching=result.matching, offset=result.offset, items=items)


# ---------------------------------------------------------------- SOAP calls

def _needs_change(env: dict) -> bool:
    """frontend/src/pages/repositories/soapNeedsChange.ts: a verdict that asks for a change in some environment."""
    return (env["runtime"].get("verdict") in ("unsupported", "supported_with_caveat")
            or env["platform"].get("verdict") in ("incompatible", "requires_change"))


_UNDECIDED = (None, "unknown", "not_assessed", "under_review")


def _undecided(env: dict) -> bool:
    return env["runtime"].get("verdict") in _UNDECIDED or env["platform"].get("verdict") in _UNDECIDED


class _SoapContext:
    """What every SOAP call's verdicts are read against: the engagement's target and live matrix entries, and the
    estate report's rows."""

    def __init__(self, db: Session, repo: models.Repository):
        self.engagement = db.get(models.Engagement, repo.engagement_id)
        self.target_wcf = self.engagement.target_wcf_client_version or wcf_matrix.target_wcf_client(
            wcf_matrix.load("support"), self.engagement.target_framework)
        applied = engagement_matrix.overlay(db, self.engagement.id)
        self.live = {kind: engagement_matrix.apply(kind, wcf_matrix.entries(kind), applied) for kind in wcf_matrix.KINDS}

    def call(self, row: models.OutboundInvocation, project_path: str, estate_host: str | None) -> dict:
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
                                                   self.target_wcf, self.live["support"], b.get("runtimeReasons")),
                "platform": wcf_matrix.live_verdict("platform", b.get("linuxVerdict") or row.linux_verdict, b.get("platformMatrixEntry"),
                                                    self.target_wcf, self.live["platform"], b.get("linuxReasons")),
            })
        return {"invocationId": row.id, "projectPath": project_path, "contract": block.get("contract"),
                "clientType": block.get("clientType"), "endpoint": surface._endpoint_display(row),
                "environments": environments, "estateHost": estate_host}


def _estate_hosts(db: Session, engagement_id: str, invocation_ids: list[str]) -> dict[str, str]:
    """Each call's row in the newest estate report (from the database, app.results)."""
    run, _ = estate_run(db, engagement_id)
    if run is None or not invocation_ids:
        return {}
    report = store.latest_estate(db, engagement_id, run.id).get("soap-backend-compatibility")
    if report is None:
        return {}
    return dict(db.execute(text("""
        select c->>'invocationId', h->>'host'
        from result_artifacts a join result_contents rc on rc.checksum = a.checksum,
             jsonb_array_elements(coalesce(rc.content->'hosts', '[]')) h, jsonb_array_elements(coalesce(h->'callers', '[]')) c
        where a.artifact_id = :a and c->>'invocationId' = any(:ids)
    """), {"a": report.artifact_id, "ids": invocation_ids}).all())


def estate_run(db: Session, engagement_id: str):
    from app.routers import estate as estate_router

    return estate_router._latest_run(db, engagement_id, contents=False)


class SoapSummaryOut(BaseModel):
    repository_id: uuid.UUID
    engagement_id: str
    scanned_at: datetime.datetime | None
    estate_run_at: datetime.datetime | None
    estate_stale: bool
    estate_note: str | None
    target_wcf_client_version: str | None
    unused_count: int
    calls: int
    environments: int = Field(description="Rows of the table: one per call and environment.")
    need_change: int = Field(description="Calls with a verdict that asks for a change in some environment.")
    undecided: int = Field(description="Calls without one, but with a verdict still unknown or under review.")


def _soap_rows(db: Session, repository_id: uuid.UUID):
    return db.query(models.OutboundInvocation).filter(models.OutboundInvocation.repository_id == repository_id,
                                                      models.OutboundInvocation.mechanism == "soap_client")


@router.get("/repositories/{repository_id}/soap-compatibility/summary", response_model=SoapSummaryOut,
            summary="Get a repository's SOAP call totals, with their live verdicts counted",
            operation_id="get_repository_soap_summary", responses=_RESPONSES)
def get_repository_soap_summary(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    """The SOAP panel's header and the Overview's figure. The verdicts are read live against the matrices, as the
    panel shows them, for every call: only the counts are sent."""
    repo = _repository(db, repository_id)
    scan = _outbound_scan(db, repository_id)
    context = _SoapContext(db, repo)
    projects = {p["projectId"]: p["projectPath"] for p in scan.project_summaries}
    calls, unused = [], 0
    for row in _soap_rows(db, repository_id):
        if row.usage != "used":
            unused += 1
            continue
        calls.append(context.call(row, projects.get(str(row.project_id), ""), None))
    need = [c for c in calls if any(_needs_change(e) for e in c["environments"])]
    undecided = [c for c in calls if c not in need and any(_undecided(e) for e in c["environments"])]
    run, _ = estate_run(db, repo.engagement_id)
    estate_run_at = run.ended_at if run is not None else None
    stale = estate_run_at is None or (scan.scanned_at is not None and scan.scanned_at > estate_run_at)
    note = None
    if estate_run_at is None:
        note = "The estate consolidation has never run for this engagement: there is no estate report to link to."
    elif stale:
        note = (f"The estate report was built {estate_run_at:%Y-%m-%d %H:%M} UTC, before this repository's last scan "
                f"({scan.scanned_at:%Y-%m-%d %H:%M} UTC). The verdicts here are the scan's; the estate report has not been "
                f"rerun since, so its totals and rows do not include this scan yet. Rerun the estate consolidation.")
    return SoapSummaryOut(repository_id=repository_id, engagement_id=repo.engagement_id, scanned_at=scan.scanned_at,
                          estate_run_at=estate_run_at, estate_stale=stale, estate_note=note,
                          target_wcf_client_version=context.target_wcf, unused_count=unused, calls=len(calls),
                          environments=sum(len(c["environments"]) for c in calls), need_change=len(need),
                          undecided=len(undecided))


@router.get("/repositories/{repository_id}/soap-compatibility/calls", response_model=PageOut,
            summary="Get a page of a repository's SOAP calls with both verdicts per environment",
            operation_id="list_repository_soap_calls", responses=_RESPONSES)
def list_repository_soap_calls(repository_id: uuid.UUID, paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as RepositorySoapCallOut, by project. The filter matches the contract, the client type, the endpoint
    and the project."""
    repo = _repository(db, repository_id)
    _outbound_scan(db, repository_id)
    source = f"""
        select jsonb_build_object('id', o.id, 'project', coalesce(ps->>'projectPath', '')) as item,
               coalesce(ps->>'projectPath', '') as k_project, o.id,
               lower(concat_ws(' ', o.detail->'block'->>'contract', o.detail->'block'->>'clientType', {_endpoint('o.')},
                               ps->>'projectPath')) as search
        from outbound_invocations o
        left join outbound_scans s on s.repository_id = o.repository_id
        left join lateral (select x from jsonb_array_elements(s.project_summaries) x
                           where x->>'projectId' = o.project_id::text limit 1) p(ps) on true
        where o.repository_id = :r and o.mechanism = 'soap_client' and o.usage = 'used'
    """
    result = page(db, source, {"r": repository_id}, paging, order='k_project collate "C", id collate "C"')
    ids = [i["id"] for i in result.items]
    if not ids:
        return result
    context = _SoapContext(db, repo)
    rows = {r.id: r for r in db.query(models.OutboundInvocation).filter(models.OutboundInvocation.id.in_(ids))}
    hosts = _estate_hosts(db, repo.engagement_id, ids)
    items = [context.call(rows[i["id"]], i["project"], hosts.get(i["id"])) for i in result.items]
    return PageOut(total=result.total, matching=result.matching, offset=result.offset, items=items)
