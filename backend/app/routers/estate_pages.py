"""The Estate tab's lists a page at a time (app.results.paging), over the newest consolidation run's artifacts in the
database: the endpoint register, its unresolved endpoints, the integration map, the package estate, the dependency
graph's lists, the SOAP report's backend hosts, and the context map whole (it is drawn whole). Read-only.

The estate's own data comes from every repository's results in the database, so these views are the same whoever's
machine ran the consolidation, and whichever machines the repositories were scanned on.
"""
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.estate import engagement_matrix
from app.results import store
from app.results.paging import PAGE, PageOut, PageParams, page
from app.routers import estate

router = APIRouter(prefix="/api/engagements", tags=["Estate"])

_RESPONSES = {404: {"model": ErrorResponse, "description": "No engagement exists with this id."},
              409: {"model": ErrorResponse, "description": "The estate consolidation has not produced this view yet."}}


def _artifact(db: Session, engagement_id: str, kind: str) -> uuid.UUID:
    """The newest run's stored artifact of this kind."""
    estate._engagement(db, engagement_id)
    run, _ = estate._latest_run(db, engagement_id, contents=False)
    stored = store.latest_estate(db, engagement_id, run.id).get(kind) if run is not None else None
    if stored is None:
        raise error(409, f"No {kind} yet: run the estate consolidation.", code="NOT_RUN")
    return stored.artifact_id


def _elements(path: str) -> str:
    """One row per element of a list of the stored content, with its position (n)."""
    return f"""
        select e as x, n
        from result_artifacts a join result_contents c on c.checksum = a.checksum,
             jsonb_array_elements(coalesce(c.content #> '{{{path}}}', '[]')) with ordinality t(e, n)
        where a.artifact_id = :a
    """


def _strings(expression: str, field: str | None = None) -> str:
    """The strings of a list inside an element, joined: what a row's filter matches on."""
    value = f"y->>'{field}'" if field else "y #>> '{}'"
    return f"(select string_agg({value}, ' ') from jsonb_array_elements(coalesce({expression}, '[]')) y)"


# ---------------------------------------------------------------- endpoint register

@router.get("/{engagement_id}/estate/register/hosts", response_model=PageOut,
            summary="Get a page of the endpoint register: its hosts, then the hosts no longer called",
            operation_id="list_register_hosts", responses=_RESPONSES)
def list_register_hosts(engagement_id: str, paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items: {host, annotation} for a host the estate calls, {noLongerCalled, annotation} for one no run calls any more
    whose annotation is kept. The annotation is live: the host's own, else one carried from a host it replaced. The
    filter matches the host, its other environments' hosts, its services and calling repositories."""
    artifact_id = _artifact(db, engagement_id, "endpoint-register")
    source = f"""
        select jsonb_build_object('host', x) as item, n as k,
               lower(concat_ws(' ', x->>'host', {_strings("x->'otherHosts'", 'host')},
                               {_strings("x->'services'", 'path')}, {_strings("x->'services'", 'contract')},
                               {_strings("x->'callingRepositories'")})) as search
        from ({_elements('hosts')}) h
        union all
        select jsonb_build_object('noLongerCalled', x #>> '{{}}'), 1000000000 + n, lower(x #>> '{{}}')
        from ({_elements('noLongerCalled')}) g
    """
    result = page(db, source, {"a": artifact_id}, paging, order="k")
    names = set()
    for row in result.items:
        if "host" in row:
            names.add(row["host"]["host"])
            names.update(row["host"].get("annotationCarriedFrom") or [])
        else:
            names.add(row["noLongerCalled"])
    slugs = estate._repository_slugs(db, engagement_id)
    annotations = {a.host: estate._annotation_out(a, slugs).model_dump(mode="json")
                   for a in db.query(models.EndpointAnnotation).filter(models.EndpointAnnotation.engagement_id == engagement_id,
                                                                       models.EndpointAnnotation.host.in_(names))} if names else {}
    items = []
    for row in result.items:
        if "host" in row:
            host = row["host"]
            annotation = annotations.get(host["host"]) or next(
                (annotations[h] for h in host.get("annotationCarriedFrom") or [] if h in annotations), None)
            items.append({"host": host, "annotation": annotation})
        else:
            items.append({"noLongerCalled": row["noLongerCalled"], "annotation": annotations.get(row["noLongerCalled"])})
    return PageOut(total=result.total, matching=result.matching, offset=result.offset, items=items)


@router.get("/{engagement_id}/estate/register/unresolved", response_model=PageOut,
            summary="Get a page of the endpoint register's unresolved endpoints", operation_id="list_register_unresolved",
            responses=_RESPONSES)
def list_register_unresolved(engagement_id: str, paging: PageParams = Depends(), db: Session = Depends(get_db)):
    artifact_id = _artifact(db, engagement_id, "endpoint-register")
    source = f"""
        select x as item, n as k,
               lower(concat_ws(' ', (x->>'repositorySlug') || ':' || (x->>'projectPath'), x->>'contract',
                               coalesce(x->>'placeholder', x->>'resolution'))) as search
        from ({_elements('unresolved')}) u
    """
    return page(db, source, {"a": artifact_id}, paging, order="k")


# ---------------------------------------------------------------- integration map

_CALLED = "(select count(*) from jsonb_array_elements(coalesce(x->'exposes', '[]')) y where jsonb_array_length(coalesce(y->'callers', '[]')) > 0)"


@router.get("/{engagement_id}/estate/integration/applications", response_model=PageOut,
            summary="Get a page of the integration map's applications", operation_id="list_integration_applications",
            responses=_RESPONSES)
def list_integration_applications(engagement_id: str,
                                  exposed: str = Query("called", pattern="^(called|all)$",
                                                       description="called: applications that call, or are called; "
                                                                   "all: also those with any entry point."),
                                  paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items: the application (repositorySlug, projectPath, repositoryId, projectId), its counts (calls, exposes,
    called, uncalled) and the first page of each of its lists (calls, called, uncalled); the rest come from
    /estate/integration/lists. The filter matches the application and every operation it calls or serves."""
    artifact_id = _artifact(db, engagement_id, "integration-map")
    source = f"""
        select x as item, n as k, jsonb_array_length(coalesce(x->'calls', '[]')) as calls,
               jsonb_array_length(coalesce(x->'exposes', '[]')) as exposes, {_CALLED} as called,
               lower(concat_ws(' ', (x->>'repositorySlug') || ':' || (x->>'projectPath'),
                               {_strings("x->'calls'", 'operation')}, {_strings("x->'exposes'", 'operation')})) as search
        from ({_elements('applications')}) a
    """
    keep = "calls > 0 or called > 0" if exposed == "called" else "calls > 0 or exposes > 0"
    result = page(db, source, {"a": artifact_id}, paging, order="k", where=keep)
    items = []
    for app in result.items:
        exposes = app.get("exposes") or []
        called = [e for e in exposes if e.get("callers")]
        uncalled = [e for e in exposes if not e.get("callers")]
        first = lambda entries: PageOut(total=len(entries), matching=len(entries), offset=0,  # noqa: E731
                                        items=entries[:PAGE]).model_dump()
        items.append({**{k: v for k, v in app.items() if k not in ("calls", "exposes")},
                      "counts": {"calls": len(app.get("calls") or []), "exposes": len(exposes), "called": len(called),
                                 "uncalled": len(uncalled)},
                      "calls": first(app.get("calls") or []), "called": first(called), "uncalled": first(uncalled)})
    return PageOut(total=result.total, matching=result.matching, offset=result.offset, items=items)


@router.get("/{engagement_id}/estate/integration/lists", response_model=PageOut,
            summary="Get a page of one application's calls, called operations or uncalled operations",
            operation_id="list_integration_application_list", responses=_RESPONSES)
def list_integration_application_list(engagement_id: str, repository_slug: str = Query(...), project_path: str = Query(...),
                                      which: str = Query(..., pattern="^(calls|called|uncalled)$"),
                                      paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """calls: the operations it calls, with their targets (filter: operation, call site, targets). called: its
    operations the estate calls, with their callers (filter: operation, callers). uncalled: those nothing in the
    estate calls (filter: operation)."""
    artifact_id = _artifact(db, engagement_id, "integration-map")
    if which == "calls":
        inner = f"""
            select y as item, m as k,
                   lower(concat_ws(' ', y->>'operation', (y->'callSite'->>'filePath') || ':' || (y->'callSite'->>'lineStart'),
                                   (select string_agg((t->>'calleeRepositorySlug') || ':' || (t->>'calleeProjectPath'), ' ')
                                    from jsonb_array_elements(coalesce(y->'targets', '[]')) t))) as search
            from ({_elements('applications')}) a, jsonb_array_elements(coalesce(x->'calls', '[]')) with ordinality s(y, m)
            where x->>'repositorySlug' = :slug and x->>'projectPath' = :path
        """
    else:
        has_callers = "jsonb_array_length(coalesce(y->'callers', '[]')) > 0"
        inner = f"""
            select y as item, m as k,
                   lower(concat_ws(' ', y->>'operation',
                                   (select string_agg((c->>'callerRepositorySlug') || ':' || (c->>'callerProjectPath'), ' ')
                                    from jsonb_array_elements(coalesce(y->'callers', '[]')) c))) as search
            from ({_elements('applications')}) a, jsonb_array_elements(coalesce(x->'exposes', '[]')) with ordinality s(y, m)
            where x->>'repositorySlug' = :slug and x->>'projectPath' = :path
              and {has_callers if which == 'called' else f'not {has_callers}'}
        """
    return page(db, inner, {"a": artifact_id, "slug": repository_slug, "path": project_path}, paging, order="k")


# ---------------------------------------------------------------- package estate

@router.get("/{engagement_id}/estate/packages", response_model=PageOut,
            summary="Get a page of the package estate", operation_id="list_estate_packages", responses=_RESPONSES)
def list_estate_packages(engagement_id: str, drift_only: bool = Query(False), paging: PageParams = Depends(),
                         db: Session = Depends(get_db)):
    """Items as the package estate's packages, in its order. The filter matches the package id."""
    artifact_id = _artifact(db, engagement_id, "package-estate")
    source = f"""
        select x as item, n as k, lower(x->>'packageId') as search,
               coalesce((x->>'estateDrift')::boolean, false) as drift
        from ({_elements('packages')}) p
    """
    return page(db, source, {"a": artifact_id}, paging, order="k", where="drift" if drift_only else "true")


# ---------------------------------------------------------------- dependency graph

def _ref(e: str) -> str:
    return f"(({e})->>'repositorySlug') || ':' || (({e})->>'projectPath')"


@router.get("/{engagement_id}/estate/dependencies/{which}", response_model=PageOut,
            summary="Get a page of one of the dependency graph's lists", operation_id="list_estate_dependencies",
            responses=_RESPONSES)
def list_estate_dependencies(engagement_id: str, which: str, paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """which: shared-libraries, cycles, cross-repository (the dependencies between repositories) or
    origin-reconciliations. Items as the dependency graph writes them, in its order."""
    artifact_id = _artifact(db, engagement_id, "dependency-graph")
    if which == "shared-libraries":
        project = _ref("x->'project'")
        source = f"select x as item, n as k, lower({project}) as search from ({_elements('sharedLibraries')}) s"
        where = "true"
    elif which == "cycles":
        source = f"""select x as item, n as k,
                            lower((select string_agg({_ref('m')}, ' ') from jsonb_array_elements(coalesce(x->'members', '[]')) m)) as search
                     from ({_elements('cycles')}) c"""
        where = "true"
    elif which == "cross-repository":
        source = f"""select x as item, n as k, coalesce((x->>'crossRepository')::boolean, false) as cross_repository,
                            lower(concat_ws(' ', {_ref("x->'from'")}, {_ref("x->'to'")}, x->>'via')) as search
                     from ({_elements('edges')}) e"""
        where = "cross_repository"
    elif which == "origin-reconciliations":
        source = f"""select x as item, n as k,
                            lower(concat_ws(' ', left(x->>'entryPointId', 12), x->>'originalOrigin', x->>'reconciledOrigin',
                                            x->>'reason')) as search
                     from ({_elements('originReconciliations')}) r"""
        where = "true"
    else:
        raise error(404, f"No dependency list '{which}'", code="NOT_FOUND")
    return page(db, source, {"a": artifact_id}, paging, order="k", where=where)


# ---------------------------------------------------------------- context map

@router.get("/{engagement_id}/estate/context-map", response_model=dict,
            summary="Get the context map, whole", operation_id="get_estate_context_map", responses=_RESPONSES)
def get_estate_context_map(engagement_id: str, db: Session = Depends(get_db)):
    """The C4 landscape is drawn whole: one system per repository and external host, and their relationships."""
    return store.content(db, _artifact(db, engagement_id, "context-map"))


# ---------------------------------------------------------------- SOAP backend compatibility

def _overlaid(db: Session, engagement_id: str, artifact_id: uuid.UUID, hosts: list[dict]) -> list[dict]:
    """These hosts with what is live: confirmations, probes, the targeted WCF client, the owning team."""
    engagement = estate._engagement(db, engagement_id)
    head = store.stored_head(db, artifact_id) or {}
    owners = [a for a in db.query(models.EndpointAnnotation).filter(
        models.EndpointAnnotation.engagement_id == engagement_id,
        models.EndpointAnnotation.host.in_([h["host"] for h in hosts]))] if hosts else []
    report = estate._soap_report({**head, "hosts": hosts}, owners, engagement, engagement_matrix.overlay(db, engagement_id))
    return report["hosts"]


def _first_callers(host: dict) -> dict:
    callers = host.get("callers") or []
    return {**{k: v for k, v in host.items() if k != "callers"}, "callerCount": len(callers),
            "callers": PageOut(total=len(callers), matching=len(callers), offset=0, items=callers[:PAGE]).model_dump()}


_HOST_SEARCH = f"""lower(concat_ws(' ', x->>'host', {_strings("x->'servedBy'")},
                         (select owning_team from endpoint_annotations a where a.engagement_id = :e and a.host = x->>'host')))"""


@router.get("/{engagement_id}/estate/soap/hosts", response_model=PageOut,
            summary="Get a page of the SOAP report's backend hosts, with their verdicts as they stand now",
            operation_id="list_soap_hosts", responses=_RESPONSES)
def list_soap_hosts(engagement_id: str, paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items: each host as the report has it, with its first page of callers (`callers`) and callerCount; the rest
    from /estate/soap/callers. Verdicts and confirmations are read live. The filter matches the host, the
    repositories serving it and its owning team."""
    artifact_id = _artifact(db, engagement_id, "soap-backend-compatibility")
    source = f"select x as item, n as k, {_HOST_SEARCH} as search from ({_elements('hosts')}) h"
    result = page(db, source, {"a": artifact_id, "e": engagement_id}, paging, order="k")
    hosts = _overlaid(db, engagement_id, artifact_id, result.items)
    return PageOut(total=result.total, matching=result.matching, offset=result.offset,
                   items=[_first_callers(h) for h in hosts])


@router.get("/{engagement_id}/estate/soap/callers", response_model=PageOut,
            summary="Get a page of one SOAP backend host's callers", operation_id="list_soap_callers",
            responses=_RESPONSES)
def list_soap_callers(engagement_id: str, host: str = Query(...), paging: PageParams = Depends(),
                      db: Session = Depends(get_db)):
    """Items as the report's callers, live. The filter matches the application, the contract and the project."""
    artifact_id = _artifact(db, engagement_id, "soap-backend-compatibility")
    row = db.execute(text(f"select x from ({_elements('hosts')}) h where x->>'host' = :host limit 1"),
                     {"a": artifact_id, "host": host}).scalar()
    if row is None:
        raise error(404, f"No SOAP backend host '{host}' in the report", code="NOT_FOUND")
    term = paging.q.lower()
    callers = row.get("callers") or []
    hit = [c for c in callers if not term or term in " ".join(
        str(c.get(k) or "") for k in ("application", "contract", "projectPath")).lower()]
    shown = hit[paging.offset:paging.offset + paging.limit]
    overlaid = _overlaid(db, engagement_id, artifact_id, [{**row, "callers": shown}])[0]["callers"] if shown else []
    return PageOut(total=len(callers), matching=len(hit), offset=paging.offset, items=overlaid)


class SoapLocateOut(BaseModel):
    host: dict | None
    position: int | None = None


@router.get("/{engagement_id}/estate/soap/locate", response_model=SoapLocateOut,
            summary="Find the SOAP report's host for one call, to show it opened from a repository's page",
            operation_id="locate_soap_call", responses=_RESPONSES)
def locate_soap_call(engagement_id: str, invocation_id: str = Query(...), db: Session = Depends(get_db)):
    """The host whose callers include the call, live, with only that caller; null when the newest report does not
    have it."""
    artifact_id = _artifact(db, engagement_id, "soap-backend-compatibility")
    row = db.execute(text(f"""
        select x, n from ({_elements('hosts')}) h
        where exists (select 1 from jsonb_array_elements(coalesce(x->'callers', '[]')) c where c->>'invocationId' = :i)
        limit 1
    """), {"a": artifact_id, "i": invocation_id}).first()
    if row is None:
        return SoapLocateOut(host=None)
    host = {**row.x, "callers": [c for c in row.x.get("callers") or [] if c.get("invocationId") == invocation_id]}
    overlaid = _overlaid(db, engagement_id, artifact_id, [host])[0]
    return SoapLocateOut(host={**overlaid, "callerCount": len(row.x.get("callers") or [])}, position=row.n)
