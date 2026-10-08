"""Part B: client impact, added by dependency-and-context-map at the
end of each run, from that run's integration edges — intra- and
cross-repository. impact-analysis traverses only its own repository's code; which
code calls which service is known only once the estate is assembled.

For each work item and computed resolution whose rules include a
`client_call_sites` rule (impact-analysis deferred it, recording it in the artifact's
deferredRules), every integration edge whose entry point is handled in a file
the resolution structurally impacts gives the caller's call-site file that
rule's action, labelled `client`, with a traversal path per call. Confidence
0.8 and above is confirmed; below, possible. A file the work item already
impacts structurally stays structural (one action per file per work item).

Replaces the engagement's client rows, then each touched summary's
client_changed and client_review (never added together) and the rollups of
every repository involved.
"""

from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import models
from app.impact import rollup

CONFIRMED_AT = 0.8
_STRENGTH = {"delete": 4, "rewrite": 3, "update": 2, "review": 1}


def _client_rule(rules: list[dict]) -> dict | None:
    return next((r for r in rules if r.get("traverse") == "client_call_sites"), None)


def apply(db: Session, engagement_id: str, step_execution_id=None) -> dict:
    """Flushes; the caller commits. Returns counts for the step's message."""
    repositories = {r.id: r for r in db.scalars(select(models.Repository).where(models.Repository.engagement_id == engagement_id))}
    old_file_repos = set(db.scalars(select(models.WorkItemImpact.file_repository_id).where(
        models.WorkItemImpact.engagement_id == engagement_id, models.WorkItemImpact.source == "client")))
    db.execute(delete(models.WorkItemImpact).where(
        models.WorkItemImpact.engagement_id == engagement_id, models.WorkItemImpact.source == "client"))

    summaries = db.scalars(select(models.ImpactSummary).where(models.ImpactSummary.engagement_id == engagement_id)).all()
    structural = defaultdict(set)   # (repo, item, project, resolution) -> {(file repo, file)}
    for r in db.scalars(select(models.WorkItemImpact).where(
            models.WorkItemImpact.engagement_id == engagement_id, models.WorkItemImpact.source == "structural",
            models.WorkItemImpact.file_path.is_not(None))):
        structural[(r.repository_id, r.item_id, r.project_path, r.resolution_id)].add((r.file_repository_id, r.file_path))

    # Entry points by (repository, handler file), with the edges that reach them.
    edges = db.execute(
        select(models.IntegrationEdge, models.EntryPoint.repository_id, models.EntryPoint.file_path,
               models.EntryPoint.handler_type)
        .join(models.EntryPoint, models.EntryPoint.id == models.IntegrationEdge.entry_point_id)
        .where(models.IntegrationEdge.engagement_id == engagement_id)
    ).all()
    by_handler_file = defaultdict(list)
    for edge, repository_id, handler_file, handler_type in edges:
        by_handler_file[(repository_id, handler_file)].append((edge, handler_type))

    resolutions = {}
    rows = 0
    touched_repos = set(old_file_repos)
    for summary in sorted(summaries, key=lambda s: (str(s.repository_id), s.item_id, s.project_path, s.resolution_id)):
        if summary.resolution_id not in resolutions:
            resolution = db.get(models.ItemResolution, summary.resolution_id)
            resolutions[summary.resolution_id] = (resolution.impact_rules if resolution else None) or []
        rule = _client_rule(resolutions[summary.resolution_id])
        key = (summary.repository_id, summary.item_id, summary.project_path, summary.resolution_id)
        own = structural.get(key, set())
        calls = defaultdict(list)   # (caller repo, call-site file) -> [(edge, handler file, handler type)]
        if rule is not None:
            for file_repo, file_path in sorted(own, key=lambda f: (str(f[0]), f[1])):
                for edge, handler_type in by_handler_file.get((file_repo, file_path), []):
                    caller = (edge.caller_repository_id, edge.call_site_file)
                    if caller not in own:
                        calls[caller].append((edge, file_path, handler_type))

        for (caller_repo, call_file), reached in sorted(calls.items(), key=lambda c: (str(c[0][0]), c[0][1])):
            reached.sort(key=lambda r: (r[0].call_site_line, r[0].operation, r[0].edge_id))
            # In call-site line order, each call once.
            paths = list(dict.fromkeys(
                f"{call_file}:{edge.call_site_line} calls {edge.operation} ({edge.mechanism}, confidence {float(edge.confidence):.2f})"
                f"{'' if caller_repo == summary.repository_id else ' from ' + _slug(repositories, caller_repo)}"
                f" ← {handler_type} in {handler_file}"
                for edge, handler_file, handler_type in reached
            ))
            confirmed = any(float(edge.confidence) >= CONFIRMED_AT for edge, _, _ in reached)
            db.add(models.WorkItemImpact(
                repository_id=summary.repository_id, engagement_id=engagement_id, item_id=summary.item_id,
                project_id=summary.project_id, project_path=summary.project_path, resolution_id=summary.resolution_id,
                file_repository_id=caller_repo, file_path=call_file, action=rule["action"],
                certainty="confirmed" if confirmed else "possible",
                reasons=[{"ruleId": rule["id"], "action": rule["action"],
                          "reason": rule.get("reason") or "Calls the service this work item converts."}],
                rule_ids=[rule["id"]], traversal_paths=paths, source="client", step_execution_id=step_execution_id,
            ))
            rows += 1
            touched_repos.add(caller_repo)
        # Changed and to review apart, as everywhere (one rule, one action).
        reviewing = rule is not None and rule["action"] == "review"
        summary.client_changed = 0 if reviewing else len(calls)
        summary.client_review = len(calls) if reviewing else 0
        touched_repos.add(summary.repository_id)
    db.flush()

    for repository_id in sorted(touched_repos, key=str):
        if repository_id in repositories:
            rollup.recompute(db, repository_id)
    return {"client_rows": rows}


def _slug(repositories: dict, repository_id) -> str:
    repository = repositories.get(repository_id)
    return repository.slug if repository is not None and getattr(repository, "slug", None) else str(repository_id)
