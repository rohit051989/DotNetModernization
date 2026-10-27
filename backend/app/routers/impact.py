"""The repository page's Impact section — 33-IMPACT-ANALYSIS.md
Part J. Read-only.

Rows come from the tables impact-analysis writes (work_item_impacts, impact_summaries,
file_impact_rollup) and the client rows dependency-and-context-map adds at the end of each
estate run. Stale summaries (Part C) are returned as stale, never as current.
Pending resolutions — neither the default nor the chosen one — are the item's
live resolutions that have no summary.

Conflicts are classified estate-wide (app/impact/conflicts.py): a repository's
conflict is a catalog rule conflict when its rule pair conflicts on more than
one pair of work items anywhere in the engagement, as of the last estate run
(impact_rule_conflicts). The engagement's rule conflicts are also served for
the Estate tab, and across engagements for the master catalog view.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.impact import conflicts as conflict_groups
from app.impact.schemas import (
    ACTIONS,
    CHANGES,
    PENDING_NOTE,
    ActionCountsOut,
    ConflictOut,
    EngagementCountOut,
    EngagementRuleConflictsOut,
    EstateInstanceOut,
    EstateRuleConflictOut,
    MasterRuleConflictOut,
    FileRollupOut,
    ImpactEntryOut,
    ImpactTotalsOut,
    PendingResolutionOut,
    RepositoryImpactOut,
    ResolutionImpactOut,
    ResolutionSummaryOut,
    RollupWorkItemOut,
    RuleConflictOut,
    RuleSideOut,
    WorkItemImpactOut,
    WorkItemSummaryOut,
)

router = APIRouter(prefix="/api", tags=["Impact"])

CLIENT_NOTE = ("Client impact (the code that calls a converted service, in this repository or another) is added by "
               "the estate job's dependency-and-context-map step from its integration edges, at the end of each run.")
_ACTION_ORDER = {a: i for i, a in enumerate(("delete", "rewrite", "update", "create", "review"))}


def _repository(db: Session, repository_id: uuid.UUID) -> models.Repository:
    repo = db.get(models.Repository, repository_id)
    if repo is None or repo.deleted_at is not None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")
    return repo


def _names(db: Session):
    """Name lookups for items and resolutions, cached for one request."""
    items: dict[str, str] = {}
    resolutions: dict[str, str] = {}

    def item(item_id: str) -> str:
        if item_id not in items:
            row = db.get(models.CatalogItem, item_id)
            items[item_id] = row.name if row is not None else item_id
        return items[item_id]

    def resolution(resolution_id: str) -> str:
        if resolution_id not in resolutions:
            row = db.get(models.ItemResolution, resolution_id)
            resolutions[resolution_id] = row.name if row is not None else resolution_id
        return resolutions[resolution_id]

    return item, resolution


def _summary_fields(s: models.ImpactSummary, name: str) -> dict:
    return dict(
        resolution_id=s.resolution_id, name=name, roles=s.roles, effective=s.effective, rules_source=s.rules_source,
        counts=ActionCountsOut(**{a: (s.counts or {}).get(a, 0) for a in ACTIONS}), changed=s.changed, created=s.created,
        to_review=s.to_review, client_changed=s.client_changed, client_review=s.client_review,
        confirmed=s.confirmed, possible=s.possible, known_limits=s.known_limits,
        stale=s.stale, stale_reason=s.stale_reason,
    )


def _summaries(db: Session, repository_id: uuid.UUID) -> list[models.ImpactSummary]:
    return (
        db.query(models.ImpactSummary)
        .filter(models.ImpactSummary.repository_id == repository_id)
        .order_by(models.ImpactSummary.item_id, models.ImpactSummary.project_path, models.ImpactSummary.resolution_id)
        .all()
    )


@router.get(
    "/repositories/{repository_id}/impact",
    response_model=RepositoryImpactOut,
    summary="Get a repository's impact: totals, hotspots, conflicts, work items and files",
    operation_id="get_repository_impact",
    responses={
        404: {"model": ErrorResponse, "description": "No repository exists with this id."},
        409: {"model": ErrorResponse, "description": "Impact analysis has not run yet for this repository."},
    },
)
def get_repository_impact(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    """Totals by action under each work item's effective resolution
    (structural and client), every hotspot and conflict naming its work
    items, each work item's computed resolutions, and the per-file view.
    409 until impact-analysis has run, so the UI can show an empty state naming it."""
    repo = _repository(db, repository_id)
    summaries = _summaries(db, repository_id)
    if not summaries:
        raise error(409, "Impact analysis has not run yet for this repository.", code="NOT_SCANNED")
    item_name, resolution_name = _names(db)

    work_items: dict[tuple[str, str], WorkItemSummaryOut] = {}
    for s in summaries:
        key = (s.item_id, s.project_path)
        if key not in work_items:
            work_items[key] = WorkItemSummaryOut(item_id=s.item_id, item_name=item_name(s.item_id), project_path=s.project_path,
                                                 effective_resolution_id="", stale=False, resolutions=[])
        w = work_items[key]
        w.resolutions.append(ResolutionSummaryOut(**_summary_fields(s, resolution_name(s.resolution_id))))
        w.stale = w.stale or s.stale
        if s.effective:
            w.effective_resolution_id = s.resolution_id
    for w in work_items.values():
        # Default (or presumptive) first, then the chosen one: the side-by-side order.
        w.resolutions.sort(key=lambda r: (0 if ("default" in r.roles or "presumptive" in r.roles) else 1, r.resolution_id))

    def rollup_item(i: dict) -> RollupWorkItemOut:
        return RollupWorkItemOut(item_id=i["itemId"], item_name=item_name(i["itemId"]), project_path=i["projectPath"],
                                 resolution_id=i["resolutionId"], resolution_name=resolution_name(i["resolutionId"]),
                                 action=i["action"], source=i["source"], rule_ids=i.get("ruleIds") or [])

    def conflict_out(c: dict) -> ConflictOut:
        return ConflictOut(file_key=c["file_key"], kind=c["kind"], first=rollup_item(c["first"]), second=rollup_item(c["second"]))

    def rule_side(i: dict) -> RuleSideOut:
        return RuleSideOut(item_id=i["itemId"], item_name=item_name(i["itemId"]), resolution_id=i["resolutionId"],
                           resolution_name=resolution_name(i["resolutionId"]), rule_ids=i.get("ruleIds") or [], action=i["action"])

    files: list[FileRollupOut] = []
    rollup_rows = (db.query(models.FileImpactRollup).filter(models.FileImpactRollup.repository_id == repository_id)
                   .order_by(models.FileImpactRollup.file_key).all())
    for row in rollup_rows:
        items = sorted(row.work_items, key=lambda i: (i["itemId"], i["projectPath"], i["source"]))
        files.append(FileRollupOut(file_key=row.file_key, work_items=[rollup_item(i) for i in items], hotspot=row.hotspot,
                                   conflicts=len(row.conflicts), includes_client=row.includes_client))
    # Grouped by the rule pair that produced them, classified estate-wide
    # (app/impact/conflicts.py): the engagement's catalog rule conflicts as of
    # the last estate run, or a pair recurring within this repository that the
    # estate run has not seen yet.
    estate = {r.rule_key: r for r in db.query(models.ImpactRuleConflict)
              .filter(models.ImpactRuleConflict.engagement_id == repo.engagement_id)}
    rule_conflicts: list[RuleConflictOut] = []
    work_item_conflicts: list[ConflictOut] = []
    for g in conflict_groups.group([(repository_id, row.file_key, row.conflicts) for row in rollup_rows if row.conflicts]):
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

    # Totals from the rollup: effective resolutions only, the files in this
    # repository, one action per file per work item. Changes, creates and
    # review marks are counted apart, so each figure adds up on its own.
    effective = [i for f in files for i in f.work_items]
    by_action = ActionCountsOut(**{a: sum(1 for i in effective if i.action == a) for a in ACTIONS})
    changed_files = [f for f in files if any(i.action in CHANGES for i in f.work_items)]
    totals = ImpactTotalsOut(
        work_items=len(work_items),
        changes=sum(1 for i in effective if i.action in CHANGES),
        files_changed=len(changed_files),
        by_action=by_action,
        creates=by_action.create,
        new_files=sum(1 for f in files if f.file_key.startswith("create:")),
        review_marks=by_action.review,
        files_to_review=sum(1 for f in files if f.work_items and all(i.action == "review" for i in f.work_items)),
        client_changes=sum(1 for i in effective if i.action in CHANGES and i.source == "client"),
        hotspots=sum(1 for f in files if f.hotspot),
        conflicts=sum(len(g.instances) for g in rule_conflicts) + len(work_item_conflicts),
        rule_conflicts=len(rule_conflicts),
        rule_conflict_work_items=sum(g.work_items for g in rule_conflicts),   # estate-wide
        work_item_conflicts=len(work_item_conflicts),
        stale_work_items=sum(1 for w in work_items.values() if w.stale),
    )
    return RepositoryImpactOut(totals=totals, hotspots=[f for f in files if f.hotspot], rule_conflicts=rule_conflicts,
                               work_item_conflicts=work_item_conflicts,
                               work_items=list(work_items.values()), files=files, client_impact_note=CLIENT_NOTE)


@router.get(
    "/repositories/{repository_id}/impact/work-item",
    response_model=WorkItemImpactOut,
    summary="Get one work item's impact: default and chosen resolutions side by side, with their files",
    operation_id="get_work_item_impact",
    responses={404: {"model": ErrorResponse, "description": "No repository, or no impact for this work item."}},
)
def get_work_item_impact(
    repository_id: uuid.UUID,
    item_id: str = Query(...),
    project_path: str = Query(...),
    db: Session = Depends(get_db),
):
    """Each computed resolution with its entries (structural from impact-analysis,
    client from dependency-and-context-map) grouped by action then path, every entry with its
    reasons, certainty and traversal paths. Other live resolutions are
    pending, with the note saying so."""
    _repository(db, repository_id)
    summaries = [s for s in _summaries(db, repository_id) if s.item_id == item_id and s.project_path == project_path]
    if not summaries:
        raise error(404, f"No impact for {item_id} on {project_path}", code="NOT_FOUND")
    item_name, resolution_name = _names(db)
    slugs = {r.id: r.slug for r in db.query(models.Repository)}

    rows = (db.query(models.WorkItemImpact)
            .filter(models.WorkItemImpact.repository_id == repository_id, models.WorkItemImpact.item_id == item_id,
                    models.WorkItemImpact.project_path == project_path)
            .all())
    resolutions = []
    for s in summaries:
        entries = [
            ImpactEntryOut(
                file_repository_slug=None if r.file_repository_id == repository_id else slugs.get(r.file_repository_id),
                file_path=r.file_path, proposed_path=r.proposed_path, description=r.description, action=r.action,
                certainty=r.certainty, source=r.source, reasons=r.reasons, traversal_paths=r.traversal_paths,
                details=r.details)
            for r in rows if r.resolution_id == s.resolution_id
        ]
        entries.sort(key=lambda e: (_ACTION_ORDER[e.action], e.source != "structural", e.file_repository_slug or "",
                                    e.file_path or e.proposed_path or ""))
        resolutions.append(ResolutionImpactOut(**_summary_fields(s, resolution_name(s.resolution_id)), entries=entries))
    resolutions.sort(key=lambda r: (0 if ("default" in r.roles or "presumptive" in r.roles) else 1, r.resolution_id))

    computed = {s.resolution_id for s in summaries}
    live = (db.query(models.ItemResolution)
            .filter(models.ItemResolution.item_id == item_id, models.ItemResolution.deleted_at.is_(None),
                    models.ItemResolution.status == "active")
            .order_by(models.ItemResolution.id)
            .all())
    pending = [PendingResolutionOut(resolution_id=r.id, name=r.name) for r in live if r.id not in computed]
    effective = next(s.resolution_id for s in summaries if s.effective)
    return WorkItemImpactOut(item_id=item_id, item_name=item_name(item_id), project_path=project_path,
                             effective_resolution_id=effective, resolutions=resolutions, pending=pending,
                             pending_note=PENDING_NOTE)


ESTATE_NOTE = ("A catalog rule conflict is a rule pair that conflicts on more than one pair of work items across the "
               "engagement's repositories, as of the last estate run. Fix it once, in the catalog rules.")


def _estate_side(side: dict, item_name, resolution_name) -> RuleSideOut:
    return RuleSideOut(item_id=side["itemId"], item_name=item_name(side["itemId"]), resolution_id=side["resolutionId"],
                       resolution_name=resolution_name(side["resolutionId"]), rule_ids=side.get("ruleIds") or [],
                       action=side["action"])


@router.get(
    "/engagements/{engagement_id}/impact/rule-conflicts",
    response_model=EngagementRuleConflictsOut,
    summary="Get an engagement's catalog rule conflicts across its estate",
    operation_id="get_engagement_rule_conflicts",
    responses={404: {"model": ErrorResponse, "description": "No engagement exists with this id."}},
)
def get_engagement_rule_conflicts(engagement_id: str, db: Session = Depends(get_db)):
    """The Estate tab's view: each rule pair conflicting on more than one pair
    of work items across the engagement, with every instance by repository."""
    if db.get(models.Engagement, engagement_id) is None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    item_name, resolution_name = _names(db)
    slugs = {str(r.id): r.slug for r in db.query(models.Repository).filter(models.Repository.engagement_id == engagement_id)}
    rows = (db.query(models.ImpactRuleConflict).filter(models.ImpactRuleConflict.engagement_id == engagement_id)
            .order_by(models.ImpactRuleConflict.work_items.desc(), models.ImpactRuleConflict.rule_key).all())
    return EngagementRuleConflictsOut(engagement_id=engagement_id, note=ESTATE_NOTE, rule_conflicts=[
        EstateRuleConflictOut(
            rule_key=r.rule_key, kind=r.kind, first=_estate_side(r.first, item_name, resolution_name),
            second=_estate_side(r.second, item_name, resolution_name), work_items=r.work_items, repositories=r.repositories,
            computed_at=r.computed_at.isoformat(),
            instances=[EstateInstanceOut(repository_id=i["repository_id"], repository_slug=slugs.get(i["repository_id"]),
                                         file_key=i["file_key"], first_project_path=i["first"]["projectPath"],
                                         second_project_path=i["second"]["projectPath"]) for i in r.instances])
        for r in rows])


@router.get(
    "/catalog/impact-rule-conflicts",
    response_model=list[MasterRuleConflictOut],
    summary="Get catalog rule conflicts across every engagement, for catalog authors",
    operation_id="list_catalog_rule_conflicts",
)
def list_catalog_rule_conflicts(db: Session = Depends(get_db)):
    """The master catalog view's: each rule pair, with the engagements whose
    estates show it as a catalog rule conflict. Counts only — which files are
    affected is each engagement's own data, on its Estate tab."""
    # Counts per engagement: everyone signed in sees every engagement (app.auth.policy), so no gate is needed.
    item_name, resolution_name = _names(db)
    names = {e.id: e.client_name for e in db.query(models.Engagement)}
    by_key: dict[str, list[models.ImpactRuleConflict]] = {}
    for r in db.query(models.ImpactRuleConflict).order_by(models.ImpactRuleConflict.rule_key, models.ImpactRuleConflict.engagement_id):
        by_key.setdefault(r.rule_key, []).append(r)
    result = [
        MasterRuleConflictOut(
            rule_key=key, kind=rows[0].kind, first=_estate_side(rows[0].first, item_name, resolution_name),
            second=_estate_side(rows[0].second, item_name, resolution_name),
            work_items=sum(r.work_items for r in rows), repositories=sum(r.repositories for r in rows),
            engagements=[EngagementCountOut(engagement_id=r.engagement_id, client_name=names.get(r.engagement_id, r.engagement_id),
                                            work_items=r.work_items, repositories=r.repositories) for r in rows])
        for key, rows in by_key.items()
    ]
    return sorted(result, key=lambda m: (-m.work_items, m.rule_key))

