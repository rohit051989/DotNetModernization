"""The repository page's Impact section a page at a time (app.results.paging): its totals, then each list (hotspots,
catalog rule conflicts, work-item conflicts, work items, files) served by the database 20 at a time with the filter
box's text. The whole-repository endpoint (app.routers.impact) stays for tools; the UI reads these. Read-only.
"""
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.impact import conflicts as conflict_groups
from app.impact.schemas import (
    ConflictOut,
    FileRollupOut,
    ImpactTotalsOut,
    ResolutionSummaryOut,
    RollupWorkItemOut,
    RuleConflictOut,
    RuleSideOut,
    WorkItemSummaryOut,
)
from app.results.paging import PAGE, PageOut, PageParams, page
from app.routers import impact

router = APIRouter(prefix="/api", tags=["Impact"])

_RESPONSES = {404: {"model": ErrorResponse, "description": "No repository exists with this id."},
              409: {"model": ErrorResponse, "description": "Impact analysis has not run yet for this repository."}}


def _ready(db: Session, repository_id: uuid.UUID) -> models.Repository:
    repo = impact._repository(db, repository_id)
    if db.query(models.ImpactSummary.repository_id).filter(models.ImpactSummary.repository_id == repository_id).first() is None:
        raise error(409, "Impact analysis has not run yet for this repository.", code="NOT_SCANNED")
    return repo


def _rollup_item(item_name, resolution_name):
    def out(i: dict) -> RollupWorkItemOut:
        return RollupWorkItemOut(item_id=i["itemId"], item_name=item_name(i["itemId"]), project_path=i["projectPath"],
                                 resolution_id=i["resolutionId"], resolution_name=resolution_name(i["resolutionId"]),
                                 action=i["action"], source=i["source"], rule_ids=i.get("ruleIds") or [])
    return out


def _conflicts(db: Session, repo: models.Repository) -> tuple[list[RuleConflictOut], list[ConflictOut]]:
    """The repository's conflicts grouped by rule pair (app.impact.conflicts), as app.routers.impact groups them: from
    the files that have any, only."""
    item_name, resolution_name = impact._names(db)
    rollup_item = _rollup_item(item_name, resolution_name)
    rows = (db.query(models.FileImpactRollup)
            .filter(models.FileImpactRollup.repository_id == repo.id,
                    func.jsonb_array_length(func.coalesce(models.FileImpactRollup.conflicts, text("'[]'::jsonb"))) > 0)
            .order_by(models.FileImpactRollup.file_key).all())
    estate = {r.rule_key: r for r in db.query(models.ImpactRuleConflict)
              .filter(models.ImpactRuleConflict.engagement_id == repo.engagement_id)}

    def conflict_out(c: dict) -> ConflictOut:
        return ConflictOut(file_key=c["file_key"], kind=c["kind"], first=rollup_item(c["first"]), second=rollup_item(c["second"]))

    def rule_side(i: dict) -> RuleSideOut:
        return RuleSideOut(item_id=i["itemId"], item_name=item_name(i["itemId"]), resolution_id=i["resolutionId"],
                           resolution_name=resolution_name(i["resolutionId"]), rule_ids=i.get("ruleIds") or [], action=i["action"])

    rule_conflicts, work_item_conflicts = [], []
    for g in conflict_groups.group([(repo.id, row.file_key, row.conflicts) for row in rows if row.conflicts]):
        instances = [conflict_out(i) for i in g["instances"]]
        known = estate.get(g["key"])
        if known is not None or conflict_groups.is_rule_conflict(g):
            rule_conflicts.append(RuleConflictOut(
                rule_key=g["key"], kind=g["kind"], first=rule_side(g["first"]), second=rule_side(g["second"]),
                work_items=known.work_items if known is not None else g["work_items"],
                repositories=known.repositories if known is not None else 1,
                classified_by="estate" if known is not None else "repository", instances=instances))
        else:
            work_item_conflicts.extend(instances)
    return rule_conflicts, work_item_conflicts


class ImpactSummaryOut(BaseModel):
    totals: ImpactTotalsOut
    client_impact_note: str
    counts: dict[str, int]


@router.get("/repositories/{repository_id}/impact/summary", response_model=ImpactSummaryOut,
            summary="Get a repository's impact totals, without its lists", operation_id="get_repository_impact_summary",
            responses=_RESPONSES)
def get_repository_impact_summary(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    """The totals, as app.routers.impact computes them, counted by the database over the file rollup, and how many
    items each list has. Conflicts are grouped from the files that have any."""
    repo = _ready(db, repository_id)
    changes = list(impact.CHANGES)
    row = db.execute(text("""
        with files as (select file_key, hotspot, coalesce(work_items, '[]'::jsonb) as items from file_impact_rollup
                       where repository_id = :r),
             effective as (select f.file_key, i->>'action' as action, i->>'source' as source
                           from files f, jsonb_array_elements(f.items) i)
        select (select count(*) from files) as files,
               (select count(*) from files where hotspot) as hotspots,
               (select count(*) from files where file_key like 'create:%') as new_files,
               (select count(*) from files f where jsonb_array_length(f.items) > 0 and not exists (
                    select 1 from jsonb_array_elements(f.items) i where i->>'action' <> 'review')) as files_to_review,
               (select count(distinct file_key) from effective where action = any(:changes)) as files_changed,
               (select count(*) from effective where action = any(:changes)) as changes,
               (select count(*) from effective where action = any(:changes) and source = 'client') as client_changes,
               (select coalesce(jsonb_object_agg(action, n), '{}'::jsonb) from (
                    select action, count(*) as n from effective group by action) a) as by_action,
               (select count(*) from (select distinct item_id, project_path from impact_summaries where repository_id = :r) w) as work_items,
               (select count(*) from (select distinct item_id, project_path from impact_summaries
                                      where repository_id = :r and stale) s) as stale
    """), {"r": repository_id, "changes": changes}).one()
    by_action = {a: row.by_action.get(a, 0) for a in impact.ACTIONS}
    rule_conflicts, work_item_conflicts = _conflicts(db, repo)
    totals = ImpactTotalsOut(
        work_items=row.work_items, changes=row.changes, files_changed=row.files_changed,
        by_action=impact.ActionCountsOut(**by_action), creates=by_action["create"], new_files=row.new_files,
        review_marks=by_action["review"], files_to_review=row.files_to_review, client_changes=row.client_changes,
        hotspots=row.hotspots,
        conflicts=sum(len(g.instances) for g in rule_conflicts) + len(work_item_conflicts),
        rule_conflicts=len(rule_conflicts),
        rule_conflict_work_items=sum(g.work_items for g in rule_conflicts),
        work_item_conflicts=len(work_item_conflicts),
        stale_work_items=row.stale,
    )
    return ImpactSummaryOut(totals=totals, client_impact_note=impact.CLIENT_NOTE,
                            counts={"hotspots": row.hotspots, "rule_conflicts": len(rule_conflicts),
                                    "work_item_conflicts": len(work_item_conflicts), "work_items": row.work_items,
                                    "files": row.files})


@router.get("/repositories/{repository_id}/impact/files", response_model=PageOut,
            summary="Get a page of a repository's impact per file", operation_id="list_impact_files", responses=_RESPONSES)
def list_impact_files(repository_id: uuid.UUID, hotspots: bool = Query(False, description="Only the hotspots."),
                      paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as FileRollupOut, by file. The filter matches the file."""
    _ready(db, repository_id)
    source = """
        select jsonb_build_object('file_key', file_key) as item, file_key as k, lower(file_key) as search, hotspot
        from file_impact_rollup where repository_id = :r
    """
    result = page(db, source, {"r": repository_id}, paging, order="k", where="hotspot" if hotspots else "true")
    keys = [i["file_key"] for i in result.items]
    rows = {r.file_key: r for r in db.query(models.FileImpactRollup).filter(
        models.FileImpactRollup.repository_id == repository_id, models.FileImpactRollup.file_key.in_(keys))} if keys else {}
    rollup_item = _rollup_item(*impact._names(db))
    items = []
    for key in keys:
        row = rows[key]
        work_items = sorted(row.work_items, key=lambda i: (i["itemId"], i["projectPath"], i["source"]))
        items.append(FileRollupOut(file_key=row.file_key, work_items=[rollup_item(i) for i in work_items], hotspot=row.hotspot,
                                   conflicts=len(row.conflicts), includes_client=row.includes_client).model_dump(mode="json"))
    return PageOut(total=result.total, matching=result.matching, offset=result.offset, items=items)


@router.get("/repositories/{repository_id}/impact/work-items", response_model=PageOut,
            summary="Get a page of a repository's work items with their computed resolutions",
            operation_id="list_impact_work_items", responses=_RESPONSES)
def list_impact_work_items(repository_id: uuid.UUID, paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as WorkItemSummaryOut, by item and project. The filter matches the item's name and the project."""
    _ready(db, repository_id)
    source = """
        select jsonb_build_object('item_id', s.item_id, 'project_path', s.project_path) as item,
               s.item_id as k_item, s.project_path as k_project,
               lower(concat_ws(' ', coalesce(ci.name, s.item_id), s.project_path)) as search
        from (select distinct item_id, project_path from impact_summaries where repository_id = :r) s
        left join catalog_items ci on ci.id = s.item_id
    """
    result = page(db, source, {"r": repository_id}, paging, order="k_item, k_project")
    item_name, resolution_name = impact._names(db)
    items = []
    for key in result.items:
        summaries = (db.query(models.ImpactSummary)
                     .filter(models.ImpactSummary.repository_id == repository_id,
                             models.ImpactSummary.item_id == key["item_id"],
                             models.ImpactSummary.project_path == key["project_path"])
                     .order_by(models.ImpactSummary.resolution_id).all())
        w = WorkItemSummaryOut(item_id=key["item_id"], item_name=item_name(key["item_id"]), project_path=key["project_path"],
                               effective_resolution_id="", stale=False, resolutions=[])
        for s in summaries:
            w.resolutions.append(ResolutionSummaryOut(**impact._summary_fields(s, resolution_name(s.resolution_id))))
            w.stale = w.stale or s.stale
            if s.effective:
                w.effective_resolution_id = s.resolution_id
        w.resolutions.sort(key=lambda r: (0 if ("default" in r.roles or "presumptive" in r.roles) else 1, r.resolution_id))
        items.append(w.model_dump(mode="json"))
    return PageOut(total=result.total, matching=result.matching, offset=result.offset, items=items)


def _slice(entries: list, paging: PageParams, names) -> PageOut:
    """A page of a list the server grouped (conflicts): only the files that have conflicts were read."""
    term = paging.q.lower()
    hit = [e for e in entries if not term or term in " ".join(n or "" for n in names(e)).lower()]
    return PageOut(total=len(entries), matching=len(hit), offset=paging.offset,
                   items=[e.model_dump(mode="json") if hasattr(e, "model_dump") else e
                          for e in hit[paging.offset:paging.offset + paging.limit]])


@router.get("/repositories/{repository_id}/impact/rule-conflicts", response_model=PageOut,
            summary="Get a page of a repository's catalog rule conflicts", operation_id="list_impact_rule_conflicts",
            responses=_RESPONSES)
def list_impact_rule_conflicts(repository_id: uuid.UUID, paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as RuleConflictOut, with only the first page of `instances` and `instance_count`; the rest from
    /impact/rule-conflicts/instances. The filter matches both sides' items and resolutions."""
    repo = _ready(db, repository_id)
    rule_conflicts, _ = _conflicts(db, repo)
    result = _slice(rule_conflicts, paging, lambda g: [g.first.item_name, g.first.resolution_name,
                                                       g.second.item_name, g.second.resolution_name])
    for g in result.items:
        g["instance_count"] = len(g["instances"])
        g["instances"] = g["instances"][:PAGE]
    return result


@router.get("/repositories/{repository_id}/impact/rule-conflicts/instances", response_model=PageOut,
            summary="Get a page of the files one catalog rule conflict hits", operation_id="list_impact_rule_conflict_instances",
            responses=_RESPONSES)
def list_impact_rule_conflict_instances(repository_id: uuid.UUID, rule_key: str = Query(...), paging: PageParams = Depends(),
                                        db: Session = Depends(get_db)):
    repo = _ready(db, repository_id)
    rule_conflicts, _ = _conflicts(db, repo)
    group = next((g for g in rule_conflicts if g.rule_key == rule_key), None)
    if group is None:
        raise error(404, f"No catalog rule conflict '{rule_key}' in this repository", code="NOT_FOUND")
    return _slice(group.instances, paging, lambda c: [c.file_key])


@router.get("/repositories/{repository_id}/impact/work-item-conflicts", response_model=PageOut,
            summary="Get a page of a repository's work-item conflicts", operation_id="list_impact_work_item_conflicts",
            responses=_RESPONSES)
def list_impact_work_item_conflicts(repository_id: uuid.UUID, paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items as ConflictOut. The filter matches the file and both work items."""
    repo = _ready(db, repository_id)
    _, work_item_conflicts = _conflicts(db, repo)
    return _slice(work_item_conflicts, paging, lambda c: [c.file_key, c.first.item_name, c.second.item_name])
