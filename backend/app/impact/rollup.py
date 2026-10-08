"""Part G, the per-file rollup, recomputed in Python once dependency-and-context-map has added
client rows. Mirrors ImpactPipeline.Rollup in impact-analysis's solution
(steps/step-003-fingerprinting/src/Fingerprinting.Impact) exactly — same
file keys, same ordering, same conflict rules — so a repository with no
client rows gets the rollup impact-analysis wrote.

From effective resolutions: a file touched by three or more work items is a
hotspot; delete with any non-delete, or two creates at one path, is a
conflict naming both work items. Rewrite with update, or update with update,
is ordering, not conflict.
"""

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app import models

_ITEM_KEYS = ("itemId", "projectPath", "resolutionId", "action", "source", "ruleIds")


def file_key(file_path: str | None, proposed_path: str | None) -> str:
    return file_path if file_path is not None else "create:" + proposed_path


def compute(entries: list[tuple[str, dict]]) -> list[dict]:
    """entries: (file key, {itemId, projectPath, resolutionId, action, source})."""
    groups: dict[str, list[dict]] = {}
    for key, item in entries:
        groups.setdefault(key, [])
        if item not in groups[key]:
            groups[key].append(item)
    result = []
    for key in sorted(groups):
        items = sorted(groups[key], key=lambda i: (i["itemId"], i["projectPath"], i["source"]))
        distinct = len({(i["itemId"], i["projectPath"]) for i in items})
        conflicts = []
        for a in range(len(items)):
            for b in range(a + 1, len(items)):
                first, second = items[a], items[b]
                if (first["itemId"], first["projectPath"]) == (second["itemId"], second["projectPath"]):
                    continue
                if (first["action"] == "delete") != (second["action"] == "delete"):
                    kind = "delete_with_change"
                elif first["action"] == "create" and second["action"] == "create":
                    kind = "create_same_path"
                else:
                    continue
                conflicts.append({"kind": kind, "first": first, "second": second})
        result.append({"fileKey": key, "workItems": items, "hotspot": distinct >= 3, "conflicts": conflicts})
    return result


def recompute(db: Session, repository_id) -> list[dict]:
    """Replaces the repository's file_impact_rollup: its own work items'
    structural rows and every client row whose file is in it, each under the
    work item's effective resolution. Flushes; the caller commits."""
    effective = {
        (s.repository_id, s.item_id, s.project_path, s.resolution_id)
        for s in db.scalars(select(models.ImpactSummary).where(models.ImpactSummary.effective.is_(True)))
    }
    rows = db.scalars(
        select(models.WorkItemImpact).where(
            models.WorkItemImpact.file_repository_id == repository_id,
            or_(models.WorkItemImpact.source == "client", models.WorkItemImpact.repository_id == repository_id),
        )
    ).all()
    entries = [
        (file_key(r.file_path, r.proposed_path),
         dict(zip(_ITEM_KEYS, (r.item_id, r.project_path, r.resolution_id, r.action, r.source, sorted(set(r.rule_ids))))))
        for r in rows
        if (r.repository_id, r.item_id, r.project_path, r.resolution_id) in effective
    ]
    files = compute(entries)
    db.execute(delete(models.FileImpactRollup).where(models.FileImpactRollup.repository_id == repository_id))
    for f in files:
        db.add(models.FileImpactRollup(
            repository_id=repository_id, file_key=f["fileKey"], work_items=f["workItems"], hotspot=f["hotspot"],
            conflicts=f["conflicts"], includes_client=any(i["source"] == "client" for i in f["workItems"]),
        ))
    db.flush()
    return files
