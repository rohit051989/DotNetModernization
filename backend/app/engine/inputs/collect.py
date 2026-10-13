"""Everything the input generator needs, read from discovery and the catalog (36-COPILOT-ENHANCED-CONVERSION
Part D). One JSON-serialisable model, sorted, so rendering is a pure function of it and two runs over the
same data produce the same files.

Only what discovery stored is read. Discovery already follows the secrets rules (29-ENTRY-POINT-AND-OUTBOUND-
INVENTORIES C5, 21-APPLICATION-FINGERPRINTING Part G): a connection string is a name, a sensitive key is a
key path. Nothing here opens a configuration file; the generator's secret check reads them only to prove
their values did not leak (app.engine.inputs.secrets).
"""
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.conversion import planner

# "Conversion ordering (docs/28 Part E): ... runs BEFORE x / runs AFTER x / runs as ONE UNIT with x".
ORDERING = re.compile(r"(?i)runs\s+(?:as\s+)?(BEFORE|AFTER|ONE UNIT with)\s+([a-z0-9-]+)")

# Version and platform changes that compile and run but give a different result: the delta categories
# the plugin's uplift_checks judges (Behavioral-silent). Item ids whose occurrences are such deltas on the
# move to a Linux container. Everything else found is listed, not judged.
SILENT_ITEMS = {
    "datetime-now-usage": "Local time is the container's (UTC by default), not the Windows server's zone",
    "encoding-default": "The default encoding differs between .NET Framework on Windows and .NET on Linux",
}


def _ordering(description: str | None) -> list[dict]:
    rules = []
    for paragraph in (description or "").split("\n"):
        if not paragraph.lower().startswith("conversion ordering"):
            continue
        for relation, other in ORDERING.findall(paragraph):
            rules.append({"relation": {"BEFORE": "before", "AFTER": "after"}.get(relation.upper(), "together"),
                          "item": other})
    return rules


def _problem(description: str | None) -> str:
    """The item's description without its ordering paragraph, which becomes prerequisites."""
    return "\n".join(p for p in (description or "").split("\n") if not p.lower().startswith("conversion ordering")).strip()


def _lines(evidence: list | None) -> list[dict]:
    out = []
    for e in evidence or []:
        if e.get("line_start") is None:
            continue
        out.append({"line": e["line_start"], "value": e.get("value"), "member": e.get("member"),
                    "type": e.get("declaring_type"), "certainty": e.get("certainty")})
    return sorted(out, key=lambda x: (x["line"], x["value"] or ""))


def collect(db: Session, repository: models.Repository) -> dict:
    engagement = db.get(models.Engagement, repository.engagement_id)
    r = repository.id

    projects = [dict(path=p, framework=f) for p, f in db.execute(text("""
        SELECT relative_path, target_framework_raw FROM projects WHERE repository_id = :r ORDER BY relative_path"""), {"r": r})]
    current = sorted({p["framework"] for p in projects if p["framework"]})

    occurrences: dict[str, list[dict]] = {}
    for item_id, project, file_path, value, certainty, evidence in db.execute(text("""
            SELECT o.item_id, p.relative_path, o.file_path, o.value, o.certainty, o.evidence
            FROM item_occurrences o JOIN projects p ON p.id = o.project_id
            WHERE o.repository_id = :r AND o.detection_state = 'found'
            ORDER BY o.item_id, p.relative_path, o.file_path NULLS FIRST, o.value NULLS FIRST"""), {"r": r}):
        occurrences.setdefault(item_id, []).append({
            "project": project, "file": file_path, "value": value, "certainty": certainty, "lines": _lines(evidence)})

    decisions = {item_id: resolution_id for item_id, resolution_id in db.execute(text("""
        SELECT item_id, resolution_id FROM engagement_decisions
        WHERE engagement_id = :e AND status <> 'superseded' AND resolution_id IS NOT NULL"""), {"e": engagement.id})}

    impact: dict[str, list[dict]] = {}
    for item_id, project, resolution_id, action, file_path, proposed, certainty, reasons in db.execute(text("""
            SELECT w.item_id, w.project_path, w.resolution_id, w.action, w.file_path, w.proposed_path, w.certainty, w.reasons
            FROM work_item_impacts w JOIN impact_summaries s ON s.repository_id = w.repository_id
             AND s.item_id = w.item_id AND s.project_path = w.project_path AND s.resolution_id = w.resolution_id
            WHERE w.repository_id = :r AND w.source = 'structural' AND s.effective
            ORDER BY w.item_id, w.project_path, COALESCE(w.file_path, w.proposed_path), w.action"""), {"r": r}):
        impact.setdefault(item_id, []).append({
            "project": project, "resolution": resolution_id, "action": action, "file": file_path,
            "proposed": proposed, "certainty": certainty,
            "reasons": sorted({(x.get("reason") if isinstance(x, dict) else str(x)) or "" for x in reasons or []})})

    items = []
    for item_id in sorted(occurrences):
        item = db.get(models.CatalogItem, item_id)
        resolutions = (db.query(models.ItemResolution).filter_by(item_id=item_id)
                       .filter(models.ItemResolution.deleted_at.is_(None)).order_by(models.ItemResolution.id).all())
        default = next((x for x in resolutions if x.is_default), None)
        decided = decisions.get(item_id)
        chosen = next((x for x in resolutions if x.id == decided), None) if decided else default
        items.append({
            "id": item_id, "name": item.name, "category": item.category, "scope": item.scope,
            "problem": _problem(item.description), "ordering": _ordering(item.description),
            "decided": decided is not None,
            "resolution": None if chosen is None else {
                "id": chosen.id, "name": chosen.name, "description": chosen.description,
                "target": chosen.target_description, "notes": chosen.notes, "consumer_impact": chosen.consumer_impact},
            "alternatives": [{"id": x.id, "name": x.name, "default": x.is_default} for x in resolutions
                             if chosen is None or x.id != chosen.id],
            "occurrences": occurrences[item_id],
            "impact": impact.get(item_id, []),
        })

    # Package moves and their couplings, as the conversion planner computes them (34-CONVERSION Part E).
    to_tfm = engagement.target_framework
    packages, couplings, drift = [], {"together": [], "depends": []}, []
    if len(current) == 1:
        found, moves, _ = planner.package_moves(db, r, current[0], to_tfm, [], drift)
        together, depends = planner.couplings(moves)
        for key, p in sorted(found.items()):
            placement, why = planner._place({"support": {p["package_id"]: p["support"]}}, current[0], to_tfm)
            packages.append({"package": p["package_id"], "from": p["from"], "to": p["to"], "outcome": p["outcome"],
                             "projects": sorted({o[1] for o in p["occurrences"]}), "retarget": placement, "why": why,
                             "dependencies_known": p["dependencies_known"]})
        couplings = {"together": [list(t) for t in together], "depends": [list(d) for d in depends]}

    deltas = []
    for delta in planner.load_deltas():
        if len(current) != 1 or not planner._crosses(current[0], to_tfm, delta["breaks_from"]):
            continue
        sites = planner._delta_findings(db, r, delta)
        if sites:
            deltas.append({"id": delta["id"], "symptom": delta.get("symptom"), "description": delta["description"],
                           "fix": (delta.get("fix") or {}).get("basis"), "sites": {k: sorted(v) for k, v in sorted(sites.items())}})

    # Names, key paths and verdicts only: never a value (a binding's deploy parameter is recorded as present).
    outbound = []
    for m, h, lv, rv, rs, bindings in db.execute(text("""
            SELECT mechanism, endpoint_host, linux_verdict, runtime_verdict, linux_reasons, environment_bindings
            FROM outbound_invocations WHERE repository_id = :r AND usage = 'used' AND linux_verdict <> 'compatible'
            ORDER BY mechanism, endpoint_host NULLS LAST, linux_verdict"""), {"r": r}):
        entry = dict(mechanism=m, host=h, linux=lv, runtime=rv, reasons=sorted(rs or []), bindings=sorted(
            ({"environment": b.get("environment"), "file": b.get("sourceFile"), "key": b.get("keyPath"),
              "linux": b.get("linuxVerdict"), "deploy_parameter": b.get("deployParameter") is not None}
             for b in bindings or []), key=lambda b: (b["file"] or "", b["key"] or "", b["environment"] or "")))
        if entry not in outbound:
            outbound.append(entry)
    soap = [dict(host=h, runtime=rv, reasons=list(rs or [])) for h, rv, rs in db.execute(text("""
        SELECT endpoint_host, runtime_verdict, runtime_reasons FROM outbound_invocations
        WHERE repository_id = :r AND runtime_verdict IS NOT NULL ORDER BY endpoint_host NULLS LAST"""), {"r": r})]

    return {
        "engagement": {"id": engagement.id, "target_framework": to_tfm, "target_platform": engagement.target_platform,
                       "posture": engagement.default_posture},
        "repository": {"slug": repository.slug, "commit": repository.ingest_commit_sha},
        "projects": projects, "current_frameworks": current,
        "items": items, "packages": packages, "couplings": couplings, "version_drift": sorted(set(drift)), "deltas": deltas,
        "outbound": outbound, "soap": soap,
    }
