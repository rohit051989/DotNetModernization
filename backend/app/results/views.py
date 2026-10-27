"""The repository page's views over its stored results (app.results): the Overview's figures and the lists of the
fingerprint, dependencies and work list, served from the database a page at a time. Read-only.

A list reads the stored artifact the view names by id, so an execution's own artifact can be shown the same way. The
items keep the artifact's own fields, so the views render them as they render the artifact; what the view used to
compute over the whole artifact (groups, counts, the order) is computed here, by the database.
"""
import datetime
import re
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.results import held, store
from app.results.paging import PAGE, PageOut, PageParams, page

router = APIRouter(prefix="/api", tags=["Results"])

_NOT_STORED = {"model": ErrorResponse, "description": "No such artifact in the database."}


# ---------------------------------------------------------------- what the repository page reads

class ResultOut(BaseModel):
    artifact_id: uuid.UUID
    job_execution_id: uuid.UUID
    created_at: datetime.datetime
    head: dict = Field(description="The artifact's top-level fields other than lists: its summary, counts, versions.")


class RepositoryResultsOut(BaseModel):
    repository_id: uuid.UUID
    results: dict[str, ResultOut] = Field(description="The newest stored artifact of each kind the page reads.")
    held_on: str | None = Field(description="Where the repository was scanned, when that is another machine: \"on Ann's "
                                            "machine (PC-17)\".")
    not_copied: int = Field(description="Kinds of result this repository has scans of whose results are not in the "
                                        "database: scans made before central results, never copied (python -m "
                                        "app.results copy-existing on the machine that made them).")
    not_copied_note: str | None = None


def _repository(db: Session, repository_id: uuid.UUID) -> models.Repository:
    repo = db.get(models.Repository, repository_id)
    if repo is None or repo.deleted_at is not None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")
    return repo


@router.get(
    "/repositories/{repository_id}/results",
    response_model=RepositoryResultsOut,
    summary="Get the newest stored result of each kind for a repository, without its lists",
    operation_id="get_repository_results",
    responses={404: {"model": ErrorResponse, "description": "No repository exists with this id."}},
)
def get_repository_results(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    """What the Overview's figures, the tab labels and each view's header read: each kind's summary and counts. The
    lists come a page at a time from the views' own endpoints."""
    repo = _repository(db, repository_id)
    rows = db.execute(text("""
        select distinct on (a.artifact_type) a.artifact_type, a.artifact_id, a.job_execution_id, a.created_at, c.head
        from result_artifacts a join result_contents c on c.checksum = a.checksum
        where a.repository_id = :r
        order by a.artifact_type, a.created_at desc, a.artifact_id desc
    """), {"r": repository_id}).all()
    results = {r.artifact_type: ResultOut(artifact_id=r.artifact_id, job_execution_id=r.job_execution_id,
                                          created_at=r.created_at, head=r.head) for r in rows}
    # Kinds scanned before central results and never copied: named, so an empty tab is explained.
    scanned = set(db.execute(text("""
        select distinct w.artifact_type
        from wf_artifacts w join wf_job_executions j on j.id = w.job_execution_id
        join wf_job_instances i on i.id = j.job_instance_id
        where i.parameters->>'repository_id' = :r and w.artifact_type = any(:types)
    """), {"r": str(repository_id), "types": list(store.REPOSITORY_TYPES)}).scalars())
    missing = sorted(scanned - set(results))
    where = held.repository_where(db, repo)
    note = None
    if missing:
        note = (f"Results of scans made before they were kept in the database ({', '.join(missing)}) are only in the run "
                f"folder of the machine that made them, {where}. They appear after the repository's next scan, or once "
                "its owner runs python -m app.results copy-existing there.")
    return RepositoryResultsOut(repository_id=repository_id, results=results,
                                held_on=where if held.elsewhere(repo.registered_host) else None,
                                not_copied=len(missing), not_copied_note=note)


def _stored(db: Session, artifact_id: uuid.UUID, artifact_type: str) -> models.ResultArtifact:
    row = db.get(models.ResultArtifact, artifact_id)
    if row is None or row.artifact_type != artifact_type:
        raise error(404, f"No {artifact_type} '{artifact_id}' in the database", code="NOT_FOUND")
    return row


# The stored content of one artifact, for the lists' sources.
_CONTENT = "select c.content from result_artifacts a join result_contents c on c.checksum = a.checksum where a.artifact_id = :a"


# ---------------------------------------------------------------- application-fingerprint

_SIGNALS = f"""
    select coalesce(s->>'category', 'UNCATEGORISED') as category, project, s
    from (
        select p->>'projectPath' as project, s
        from ({_CONTENT}) d, jsonb_array_elements(coalesce(d.content->'projects', '[]')) p,
             jsonb_array_elements(coalesce(p->'signals', '[]')) s
        union all
        select '(repository)', s
        from ({_CONTENT}) d, jsonb_array_elements(coalesce(d.content->'repositorySignals', '[]')) s
    ) x
"""


class SignalCategoryOut(BaseModel):
    category: str
    signals: int
    distinct: int


class FingerprintOverviewOut(BaseModel):
    status_counts: dict[str, int] = Field(description="Projects by fingerprintStatus.")
    categories: list[SignalCategoryOut] = Field(description="Every signal category, most signals first: bounded by the "
                                                            "signal registry.")


@router.get(
    "/results/{artifact_id}/fingerprint",
    response_model=FingerprintOverviewOut,
    summary="Get a stored application fingerprint's categories and project statuses",
    operation_id="get_fingerprint_overview",
    responses={404: _NOT_STORED},
)
def get_fingerprint_overview(artifact_id: uuid.UUID, db: Session = Depends(get_db)):
    _stored(db, artifact_id, "application-fingerprint")
    categories = db.execute(text(f"""
        select category, count(*) as signals, count(distinct coalesce(s->>'name', '')) as distinct
        from ({_SIGNALS}) x group by category order by count(*) desc, category
    """), {"a": artifact_id}).all()
    statuses = db.execute(text(f"""
        select coalesce(p->>'fingerprintStatus', 'UNKNOWN') as status, count(*) as n
        from ({_CONTENT}) d, jsonb_array_elements(coalesce(d.content->'projects', '[]')) p
        group by 1 order by 1
    """), {"a": artifact_id}).all()
    return FingerprintOverviewOut(status_counts={s.status: s.n for s in statuses},
                                  categories=[SignalCategoryOut(category=c.category, signals=c.signals, distinct=c.distinct)
                                              for c in categories])


@router.get(
    "/results/{artifact_id}/fingerprint/signals",
    response_model=PageOut,
    summary="Get a page of one signal category of a stored application fingerprint",
    operation_id="list_fingerprint_signals",
    responses={404: _NOT_STORED},
)
def list_fingerprint_signals(artifact_id: uuid.UUID, category: str = Query(...), paging: PageParams = Depends(),
                             db: Session = Depends(get_db)):
    """Items: name, value, project ("(repository)" for a repository-wide signal), sourcePath, occurrences and
    confidence; by name, then project. The filter matches name, value and project."""
    _stored(db, artifact_id, "application-fingerprint")
    source = f"""
        select jsonb_build_object('name', coalesce(s->>'name', ''), 'value', s->>'value', 'project', project,
                                  'sourcePath', s->>'sourcePath',
                                  'occurrences', coalesce((s->>'occurrenceCount')::numeric, 1),
                                  'confidence', coalesce((s->>'extractionConfidence')::numeric, 1)) as item,
               lower(concat_ws(' ', s->>'name', s->>'value', project)) as search,
               lower(coalesce(s->>'name', '')) as k_name, lower(project) as k_project
        from ({_SIGNALS}) x where category = :category
    """
    return page(db, source, {"a": artifact_id, "category": category}, paging, order="k_name, k_project")


# ---------------------------------------------------------------- dependency-assessment

# Part G's order: no compatible version first, then vulnerable, then breaking, unknown, safe and current.
_RANK = """case when pk->>'outcome' = 'no_compatible_version' then 0
                when jsonb_typeof(pk->'vulnerable') = 'object' then 1
                else 2 + coalesce(array_position(array['no_compatible_version', 'upgrade_breaking', 'framework_provided',
                                                       'unknown', 'upgrade_safe', 'current'], pk->>'outcome') - 1, 0) end"""

_USES = f"""
    select p->>'projectPath' as project, pk, lower(coalesce(pk->>'packageId', '')) as pid,
           coalesce(pk->>'currentVersion', '—') as ver, {_RANK} as rank
    from ({_CONTENT}) d, jsonb_array_elements(coalesce(d.content->'projects', '[]')) p,
         jsonb_array_elements(coalesce(p->'packages', '[]')) pk
"""


def _version_key(version: str):
    """The order of versions as the view shows them: numbers compared as numbers."""
    return [(0, int(part), "") if part.isdigit() else (1, 0, part.lower()) for part in re.split(r"(\d+)", version) if part]


@router.get(
    "/results/{artifact_id}/dependencies/feeds",
    response_model=list[dict],
    summary="Get the feeds a stored dependency assessment was answered from",
    operation_id="list_dependency_feeds",
    responses={404: _NOT_STORED},
)
def list_dependency_feeds(artifact_id: uuid.UUID, db: Session = Depends(get_db)):
    """Each feed once (by url and role), by role: a handful, so not paged."""
    _stored(db, artifact_id, "dependency-assessment")
    feeds = db.execute(text(f"""
        select distinct on (f->>'url', f->>'role') f
        from ({_CONTENT}) d, jsonb_array_elements(coalesce(d.content->'projects', '[]')) p,
             jsonb_array_elements(coalesce(p->'feeds', '[]')) f
        order by f->>'url', f->>'role'
    """), {"a": artifact_id}).scalars().all()
    return sorted(feeds, key=lambda f: f.get("role") or "")


@router.get(
    "/results/{artifact_id}/dependencies/packages",
    response_model=PageOut,
    summary="Get a page of the packages of a stored dependency assessment",
    operation_id="list_dependency_packages",
    responses={404: _NOT_STORED},
)
def list_dependency_packages(artifact_id: uuid.UUID, show_current: bool = Query(False), paging: PageParams = Depends(),
                             db: Session = Depends(get_db)):
    """One item per package id: packageId, drift, projectCount and its versions, each with the projects referencing
    it there (useCount, the first 20 as `projects`), the outcomes they have, the worst project's assessment (`worst`)
    and where the first declares it. What blocks first comes first. Without show_current, a package current
    everywhere is left out unless it drifts. The filter matches the package id and the projects' paths."""
    _stored(db, artifact_id, "dependency-assessment")
    source = f"""
        select jsonb_build_object('pid', pid) as item, pid as k_pid, min(rank) as rank, min(pk->>'packageId') as display,
               count(distinct ver) as versions, bool_and(pk->>'outcome' = 'current') as all_current,
               lower(min(pk->>'packageId') || ' ' || string_agg(project, ' ')) as search
        from ({_USES}) u group by pid
    """
    where = "true" if show_current else "(versions > 1 or not all_current)"
    result = page(db, source, {"a": artifact_id}, paging, order="rank, lower(display), k_pid", where=where)
    pids = [i["pid"] for i in result.items]
    if not pids:
        return result
    versions = db.execute(text(f"""
        select pid, ver, count(*) as use_count,
               (array_agg(pk->>'packageId' order by project))[1] as package_id,
               array_agg(distinct coalesce(pk->>'outcome', '')) as outcomes,
               (array_agg(jsonb_build_object('project', project, 'pkg', pk) order by rank, project))[1] as worst,
               (array_agg(jsonb_build_object('project', project, 'declaredAt', pk->'declaredAt') order by project))[1] as first,
               (array_agg(project order by project))[1:{PAGE}] as projects
        from ({_USES}) u where pid = any(:pids) group by pid, ver
    """), {"a": artifact_id, "pids": pids}).all()
    by_pid: dict[str, list] = {}
    for v in versions:
        by_pid.setdefault(v.pid, []).append(v)
    distinct_projects = dict(db.execute(text(f"""
        select pid, count(distinct project) from ({_USES}) u where pid = any(:pids) group by pid
    """), {"a": artifact_id, "pids": pids}).all())
    items = []
    for pid in pids:
        rows = sorted(by_pid.get(pid, []), key=lambda v: _version_key(v.ver))
        items.append({
            "packageId": rows[0].package_id if rows else pid,
            "drift": len(rows) > 1,
            "projectCount": distinct_projects.get(pid, 0),
            "versions": [{"version": v.ver, "useCount": v.use_count, "outcomes": sorted(v.outcomes), "worst": v.worst,
                          "first": v.first, "projects": v.projects} for v in rows],
        })
    return PageOut(total=result.total, matching=result.matching, offset=result.offset, items=items)


@router.get(
    "/results/{artifact_id}/dependencies/uses",
    response_model=PageOut,
    summary="Get a page of the projects referencing one package at one version, with their assessments",
    operation_id="list_dependency_uses",
    responses={404: _NOT_STORED},
)
def list_dependency_uses(artifact_id: uuid.UUID, package_id: str = Query(...),
                         version: str | None = Query(None, description="One version; none: every version in use."),
                         paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items: project and pkg, the project's own assessment of the package; by project (then version). The filter
    matches the project's path."""
    _stored(db, artifact_id, "dependency-assessment")
    source = f"""
        select jsonb_build_object('project', project, 'pkg', pk) as item, lower(project) as search, project as k, ver
        from ({_USES}) u where pid = lower(:package_id) and (cast(:version as text) is null or ver = :version)
    """
    return page(db, source, {"a": artifact_id, "package_id": package_id, "version": version}, paging, order="k, ver")


@router.get(
    "/results/{artifact_id}/dependencies/project",
    response_model=dict | None,
    summary="Get one project's entry in a stored dependency assessment",
    operation_id="get_dependency_project",
    responses={404: _NOT_STORED},
)
def get_dependency_project(artifact_id: uuid.UUID, path: str = Query(...), db: Session = Depends(get_db)):
    """The project's status, reason and packages, for the dependency graph's details panel; null when the project is
    not in the assessment."""
    _stored(db, artifact_id, "dependency-assessment")
    return db.execute(text(f"""
        select p from ({_CONTENT}) d, jsonb_array_elements(coalesce(d.content->'projects', '[]')) p
        where lower(p->>'projectPath') = lower(:path) limit 1
    """), {"a": artifact_id, "path": path}).scalar()


# ---------------------------------------------------------------- item-occurrences: the work list

# One row per item in a project, with what the list sorts and counts by. A found item's files are its located
# occurrences; `possible` those whose every piece of evidence is ambiguous.
_GROUPS = f"""
    select p->>'projectPath' as project, p->>'projectId' as project_id, i as item,
           coalesce(i->>'itemId', '') as item_id, coalesce(i->>'detectionState', '') as state,
           coalesce(o.files, 0) as files, coalesce(o.possible, 0) as possible
    from ({_CONTENT}) d, jsonb_array_elements(coalesce(d.content->'projects', '[]')) p,
         jsonb_array_elements(coalesce(p->'items', '[]')) i
         left join lateral (
             select count(*) filter (where coalesce(e->>'filePath', '') <> '') as files,
                    count(*) filter (where coalesce(e->>'filePath', '') <> '' and e->>'certainty' = 'possible') as possible
             from jsonb_array_elements(coalesce(i->'occurrences', '[]')) e
             where i->>'detectionState' = 'found'
         ) o on true
"""
_STATE_RANK = """case g.state when 'found' then 0 when 'not_checked' then 1 when 'excluded' then 2
                            when 'checked_absent' then 3 when 'skipped' then 4 else 9 end"""


class WorkItemTotalsOut(BaseModel):
    occurrence_rows: int = Field(description="Found occurrences, one per file; an unlocated found item counts one.")
    possible_rows: int = Field(description="Of those, the ones whose every piece of evidence is ambiguous.")


@router.get(
    "/results/{artifact_id}/work-items/totals",
    response_model=WorkItemTotalsOut,
    summary="Get the occurrence totals of a stored work list",
    operation_id="get_work_item_totals",
    responses={404: _NOT_STORED},
)
def get_work_item_totals(artifact_id: uuid.UUID, db: Session = Depends(get_db)):
    _stored(db, artifact_id, "item-occurrences")
    row = db.execute(text(f"""
        select coalesce(sum(greatest(files, 1)), 0) as occurrences, coalesce(sum(possible), 0) as possible
        from ({_GROUPS}) g where state = 'found'
    """), {"a": artifact_id}).one()
    return WorkItemTotalsOut(occurrence_rows=row.occurrences, possible_rows=row.possible)


def _work_file(occurrence: dict) -> dict:
    evidence = occurrence.get("evidence") or []
    line = (evidence[0] or {}).get("line_start") if evidence and isinstance(evidence[0], dict) else None
    return {"filePath": occurrence.get("filePath") or "", "line": line or None, "value": occurrence.get("value"),
            "certainty": occurrence.get("certainty") or "confirmed"}


def _sorted_files(item: dict) -> list[dict]:
    files = [_work_file(o) for o in item.get("occurrences") or [] if o.get("filePath")]
    return sorted(files, key=lambda f: (f["certainty"] == "possible", f["filePath"].lower(), (f["value"] or "").lower()))


def _by_file(files: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for f in files:
        grouped.setdefault(f["filePath"], []).append({"value": f["value"], "line": f["line"], "certainty": f["certainty"]})
    return [{"filePath": path, "values": values} for path, values in grouped.items()]


def _first_page(entries: list[dict]) -> dict:
    """A row's nested list, its first page sent with the row so opening the list costs no request."""
    return PageOut(total=len(entries), matching=len(entries), offset=0, items=entries[:PAGE]).model_dump()


@router.get(
    "/results/{artifact_id}/work-items",
    response_model=PageOut,
    summary="Get a page of a stored work list, with each row's decision",
    operation_id="list_work_items",
    responses={404: _NOT_STORED},
)
def list_work_items(artifact_id: uuid.UUID, show_all: bool = Query(False), paging: PageParams = Depends(),
                    db: Session = Depends(get_db)):
    """One item per item in a project: itemId, name (the catalog's), groupBy, scope, project, projectId, attribute,
    state, reason, fileCount, possibleCount, distinctFiles, the first page of its files (`files`: occurrences, or
    files with their values for a value-grouped item), evidencePaths, and `decision` (the engagement's decision for
    the item, and what another item's decision means for it on this project). Found first, then not checked; without
    show_all, only those two. The filter matches the item's name and id and the project's path."""
    stored = _stored(db, artifact_id, "item-occurrences")
    source = f"""
        select jsonb_build_object('project', g.project, 'projectId', g.project_id, 'item', g.item,
                                  'name', ci.name, 'groupBy', coalesce(ci.detection->'occurrence_source'->>'group_by', 'source_path'),
                                  'fileCount', g.files, 'possibleCount', g.possible) as item,
               lower(concat_ws(' ', ci.name, g.item_id, g.project)) as search,
               {_STATE_RANK} as k_state, g.item_id as k_item, (g.files > 0 and g.possible = g.files) as k_possible,
               g.project as k_project, g.state
        from ({_GROUPS}) g left join catalog_items ci on ci.id = g.item_id
    """
    where = "true" if show_all else "state in ('found', 'not_checked')"
    result = page(db, source, {"a": artifact_id}, paging, order="k_state, k_item, k_possible, k_project", where=where)

    from app.routers import item_decisions

    projects = {r["projectId"] for r in result.items if r.get("projectId")}
    decisions = item_decisions.work_list_decisions(db, stored.repository_id, project_ids=projects) if stored.repository_id else None
    items = []
    for row in result.items:
        item = row["item"]
        state = item.get("detectionState") or ""
        files = _sorted_files(item) if state == "found" else []
        occurrences = item.get("occurrences") or []
        evidence_paths = [] if files else sorted({e.get("source_path") for o in occurrences for e in (o.get("evidence") or [])
                                                  if isinstance(e, dict) and e.get("source_path")})
        by_value = row["groupBy"] == "source_path_and_value"
        item_id = item.get("itemId") or ""
        note = None
        if decisions is not None:
            for p in decisions.projects:
                if p.project_id == row["projectId"]:
                    note = p.items.get(item_id)
        decision = decisions.decisions.get(item_id) if decisions is not None else None
        items.append({
            "itemId": item_id, "name": row.get("name"), "groupBy": row["groupBy"], "scope": item.get("scope") or "",
            "project": row["project"] or "", "projectId": row["projectId"] or "",
            "attribute": next((o.get("value") for o in occurrences if o.get("value")), None) if item.get("scope") == "application" else None,
            "state": state, "reason": item.get("reason"),
            "fileCount": len(files), "possibleCount": sum(1 for f in files if f["certainty"] == "possible"),
            "distinctFiles": len({f["filePath"] for f in files}),
            "files": _first_page(_by_file(files) if by_value else files),
            "evidencePaths": evidence_paths,
            "decision": decision.model_dump(mode="json") if decision is not None else None,
            "note": note.model_dump(mode="json") if note is not None else None,
        })
    return PageOut(total=result.total, matching=result.matching, offset=result.offset, items=items)


@router.get(
    "/results/{artifact_id}/work-items/files",
    response_model=PageOut,
    summary="Get a page of one work-list row's files",
    operation_id="list_work_item_files",
    responses={404: _NOT_STORED},
)
def list_work_item_files(artifact_id: uuid.UUID, project_id: str = Query(...), item_id: str = Query(...),
                         by_file: bool = Query(False, description="Files with their values (a value-grouped item), "
                                                                  "rather than one item per occurrence."),
                         paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Occurrences (filePath, line, value, certainty), confirmed first, then by file and value; or, by_file, each
    file once with its values. The filter matches the file's path and the values."""
    _stored(db, artifact_id, "item-occurrences")
    item = db.execute(text(f"""
        select i from ({_CONTENT}) d, jsonb_array_elements(coalesce(d.content->'projects', '[]')) p,
             jsonb_array_elements(coalesce(p->'items', '[]')) i
        where p->>'projectId' = :project and i->>'itemId' = :item limit 1
    """), {"a": artifact_id, "project": project_id, "item": item_id}).scalar()
    if item is None:
        raise error(404, f"No {item_id} on project {project_id} in this work list", code="NOT_FOUND")
    files = _sorted_files(item) if item.get("detectionState") == "found" else []
    entries = _by_file(files) if by_file else files
    term = paging.q.lower()
    if by_file:
        hit = [e for e in entries if not term or term in " ".join([e["filePath"], *[v["value"] or "" for v in e["values"]]]).lower()]
    else:
        hit = [e for e in entries if not term or term in f"{e['filePath']} {e['value'] or ''}".lower()]
    # One row's occurrences, from one item of the stored content: sliced here.
    return PageOut(total=len(entries), matching=len(hit), offset=paging.offset,
                   items=hit[paging.offset:paging.offset + paging.limit])
