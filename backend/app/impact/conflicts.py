"""Conflicts grouped by the rules that produce them — 33-IMPACT-ANALYSIS.md
Part G, as implemented.

A conflict produced by catalog rules recurs identically on every instance of
a pattern: the same item, resolution and rules on one side, the same on the
other, wherever the pattern appears. One produced by a repository's own code
is a genuine decision about that code. So each conflict has a **rule-pair
key**: its kind and its two sides' (item, resolution, rule ids).

Classification is **estate-wide**. impact-analysis records each conflict per
repository, with the rule ids that carry its key. At the end of each
estate-consolidation run, dependency-and-context-map calls `apply_estate`,
which aggregates the keys across every repository in the engagement:

- a key seen on more than one pair of work items anywhere in the estate is a
  **catalog rule conflict** ("1 rule conflict affecting N work items across M
  repositories"), stored in `impact_rule_conflicts`, for catalog authors to
  fix once in the rules;
- every other conflict is a **work-item conflict**, for a person to decide.

The repository summary classifies its own conflicts against that table, so a
conflict that occurs once in a repository is still labelled a catalog rule
conflict when its rule pair recurs elsewhere. Until the next estate run, a
key the table does not hold yet is classified from the repository alone.

A work item is an item on a project in a repository. Two files where the same
two work items conflict by the same rules are one pair: a single instance
cannot show a recurring pattern.
"""

import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import models


def side_key(side: dict) -> tuple:
    return side["itemId"], side["resolutionId"], tuple(sorted(side.get("ruleIds") or ()))


def _side_text(side: dict) -> str:
    item, resolution, rules = side_key(side)
    return f"{item}:{resolution}:{','.join(rules)}"


def ordered(conflict: dict) -> tuple[dict, dict]:
    """The two sides in key order, so a pair reads the same either way round."""
    return tuple(sorted((conflict["first"], conflict["second"]), key=side_key))  # type: ignore[return-value]


def rule_key(conflict: dict) -> str:
    """kind|item:resolution:rules|item:resolution:rules — stable across runs."""
    first, second = ordered(conflict)
    return f"{conflict['kind']}|{_side_text(first)}|{_side_text(second)}"


def _work_item(repository_id, side: dict) -> tuple:
    return str(repository_id), side["itemId"], side["projectPath"]


def group(rows: list[tuple]) -> list[dict]:
    """rows: (repository id, file key, conflicts) per file. One group per
    rule-pair key: {key, kind, first, second, pairs, work_items,
    repositories, instances: [{repository_id, file_key, kind, first, second}]},
    in key order."""
    groups: dict[str, dict] = {}
    for repository_id, file_key, conflicts in rows:
        for conflict in conflicts:
            first, second = ordered(conflict)
            key = rule_key(conflict)
            g = groups.setdefault(key, {"key": key, "kind": conflict["kind"], "first": first, "second": second, "instances": []})
            g["instances"].append({"repository_id": str(repository_id), "file_key": file_key, "kind": conflict["kind"],
                                   "first": first, "second": second})
    for g in groups.values():
        pairs = {(_work_item(i["repository_id"], i["first"]), _work_item(i["repository_id"], i["second"])) for i in g["instances"]}
        g["pairs"] = len(pairs)
        g["work_items"] = len({w for pair in pairs for w in pair})
        g["repositories"] = len({i["repository_id"] for i in g["instances"]})
        g["instances"].sort(key=lambda i: (i["repository_id"], i["file_key"]))
    return [groups[k] for k in sorted(groups)]


def is_rule_conflict(g: dict) -> bool:
    """More than one pair of work items: the threshold for a catalog rule conflict."""
    return g["pairs"] > 1


def _side_out(side: dict) -> dict:
    return {"itemId": side["itemId"], "resolutionId": side["resolutionId"], "ruleIds": sorted(side.get("ruleIds") or []),
            "action": side["action"]}


def apply_estate(db: Session, engagement_id: str, step_execution_id=None) -> dict:
    """Replaces the engagement's impact_rule_conflicts from every repository's
    rollup. Flushes; the caller commits. Called by dependency-and-context-map
    after client impact, so client rows are in the rollups it reads."""
    repositories = db.scalars(select(models.Repository.id).where(
        models.Repository.engagement_id == engagement_id, models.Repository.deleted_at.is_(None))).all()
    rows = [(r.repository_id, r.file_key, r.conflicts)
            for r in db.scalars(select(models.FileImpactRollup).where(models.FileImpactRollup.repository_id.in_(repositories)))
            if r.conflicts]
    groups = [g for g in group(rows) if is_rule_conflict(g)]
    db.execute(delete(models.ImpactRuleConflict).where(models.ImpactRuleConflict.engagement_id == engagement_id))
    now = datetime.datetime.now(datetime.timezone.utc)
    for g in groups:
        db.add(models.ImpactRuleConflict(
            engagement_id=engagement_id, rule_key=g["key"], kind=g["kind"], first=_side_out(g["first"]),
            second=_side_out(g["second"]), work_items=g["work_items"], repositories=g["repositories"],
            instances=g["instances"], computed_at=now, step_execution_id=step_execution_id,
        ))
    db.flush()
    return {"rule_conflicts": len(groups), "work_items": sum(g["work_items"] for g in groups)}
