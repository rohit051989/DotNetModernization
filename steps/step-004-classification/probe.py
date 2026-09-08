"""Pattern probing — the supported way to ask "what would match a project
that looks like pattern X?" without a repository or a scan.

**Why this module exists.** The obvious way to probe a pattern is to hand
`classify_project()` a hand-written signal set covering the pattern's
required conditions. That is wrong, and wrong in a way that looks like a
catalog bug rather than a harness bug: required conditions alone score
`base_score` 50 (Part E), and most patterns set `thresholds.minimumScore`
to 60-70. So a perfectly correct pattern reports `matched: False` and the
project reports `NO_PATTERN_MATCHED`, and the reader concludes the rules are
broken. That happened during the eShopPorted investigation and cost a round
trip.

`build_project()` therefore satisfies required conditions **and** adds
supporting conditions until the score clears the pattern's own threshold, so
a correct pattern always scores as matching. `probe()` then classifies and,
when the target pattern still does not match, says which of the four
distinct reasons applies — in particular naming insufficient supporting
weight explicitly, rather than reporting a bare non-match.

    .venv/Scripts/python.exe probe.py aspnetcore-rest-api-legacy
    .venv/Scripts/python.exe probe.py --audit
"""

import json
import sys
from pathlib import Path

import db
from engine import classify, registry

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
STEP_DIR = Path(__file__).resolve().parent

BASE_SCORE = 50  # Part E step 6. Mirrored here only to explain shortfalls.


def _database_url() -> str:
    env_path = PLATFORM_ROOT / "backend" / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError(f"DATABASE_URL not found in {env_path}")


def _latest_config() -> dict:
    candidates = sorted((STEP_DIR / "config").glob("classification-config-*.json"))
    return json.loads(candidates[-1].read_text(encoding="utf-8"))


def load_catalog() -> list[dict]:
    import main as step4main

    with db.connect(_database_url()) as conn:
        return [step4main._pattern_for_engine(r) for r in db.load_active_catalog(conn)]


# ---------- signal synthesis ----------


def _value_for(matcher: dict | None) -> str | None:
    """A value that satisfies a condition's value matcher, or None when the
    condition does not constrain the value."""
    if not matcher:
        return None
    if matcher.get("equals") is not None:
        return matcher["equals"]
    if matcher.get("in"):
        return matcher["in"][0]
    if matcher.get("startsWith"):
        return matcher["startsWith"] + "Probe"
    if matcher.get("contains"):
        return "probe-" + matcher["contains"] + "-probe"
    if matcher.get("regex"):
        # Not derivable in general. Caller is told rather than silently
        # handed a row that fails the filter.
        return None
    return None


def _rows_for_condition(condition: dict, entries: dict[str, dict]) -> list[dict]:
    """Signal rows that satisfy one condition's filters and quantifiers."""
    sig = condition["signal"]
    entry = entries.get(sig["name"], {})
    occurrences = max(1, sig.get("minimumOccurrences") or 1)
    distinct_values = sig.get("minimumDistinctValues") or 1
    distinct_files = sig.get("minimumDistinctSourceFiles") or 1
    row_count = max(distinct_values, distinct_files, 1)
    base_value = _value_for(sig.get("value"))
    confidence = sig.get("minimumExtractionConfidence") or 1.0

    rows = []
    for i in range(row_count):
        value = base_value if base_value is not None else None
        if value is not None and distinct_values > 1:
            value = f"{value}{i}"
        rows.append(
            {
                "signal_category": sig.get("category") or entry.get("category") or "SOURCE_CONSTRUCT",
                "signal_type": sig.get("type") or entry.get("type") or "ATTRIBUTE",
                "value": value,
                "source_type": sig.get("sourceType") or "SOURCE_CODE",
                "source_path": f"probe/File{i}.cs",
                # Spread the required occurrences across the rows so the
                # summed total still clears minimumOccurrences.
                "occurrence_count": max(1, -(-occurrences // row_count)),
                "extraction_confidence": confidence,
            }
        )
    return rows


def _metadata_for(pattern: dict) -> dict:
    """Project metadata satisfying the pattern's metadata conditions, with
    neutral defaults elsewhere."""
    meta = {
        "outputType": None,
        "projectFormat": "sdk_style",
        "frameworkFamily": None,
        "frameworkVersion": None,
        "projectSdk": None,
        "structuralType": "csharp_project",
        "extension": ".csproj",
        "fingerprintStatus": "COMPLETE",
    }
    for cond in pattern["detection_rules"].get("metadata") or []:
        value = _value_for(cond) or _value_for({k: cond.get(k) for k in ("equals", "in", "startsWith", "contains")})
        if value is not None:
            meta[cond["field"]] = value
    return meta


def _capabilities_for(pattern: dict) -> dict:
    caps = {
        "fileDiscovery": True,
        "syntaxAnalysis": True,
        "configurationParsed": True,
        "generatedCodeExcluded": True,
        "projectMetadataParsed": True,
        "msbuildEvaluated": True,
        "semanticAnalysis": True,
        "deploymentArtifactsParsed": True,
    }
    requirements = (pattern.get("analysis_requirements") or {}).get("required") or {}
    caps.update({k: True for k, needed in requirements.items() if needed})
    return caps


def build_project(pattern: dict, entries: dict[str, dict], metadata_overrides: dict | None = None) -> tuple[dict, dict]:
    """A synthetic project that should match `pattern`, plus a report of how
    it was built.

    Required conditions come first (`all`, one member of `any`, `count`
    members of each `atLeast` group). Supporting conditions are then added in
    descending weight until `base_score + supporting >= minimumScore`, which
    is the step the naive approach omits. Nothing from the pattern's own
    `none` list is ever added.
    """
    rules = pattern["detection_rules"]
    signals: dict[str, list[dict]] = {}
    notes: list[str] = []
    undrivable: list[str] = []

    def add(condition: dict) -> None:
        name = condition["signal"]["name"]
        if name not in entries:
            undrivable.append(f"{condition.get('id')}: {name} is not in the active signal registry")
            return
        if condition["signal"].get("value", {}) and condition["signal"]["value"].get("regex"):
            undrivable.append(f"{condition.get('id')}: value regex cannot be synthesised")
        signals.setdefault(name, []).extend(_rows_for_condition(condition, entries))

    for cond in rules.get("all") or []:
        add(cond)
    any_group = rules.get("any") or []
    if any_group:
        add(any_group[0])
        notes.append(f"any group: satisfied via '{any_group[0].get('id')}' ({len(any_group)} alternatives)")
    for group in rules.get("atLeast") or []:
        needed = group["count"]
        for cond in (group.get("of") or [])[:needed]:
            add(cond)
        notes.append(f"atLeast '{group.get('id')}': satisfied {needed} of {len(group.get('of') or [])}")

    # Supporting weight, descending, until the threshold is cleared.
    minimum = pattern["thresholds"]["minimumScore"]
    supporting = sorted(rules.get("supporting") or [], key=lambda c: -c["weight"])
    disqualifiers = {c["signal"]["name"] for c in (rules.get("none") or []) if c.get("disqualify")}
    added_weight = 0.0
    used = []
    for cond in supporting:
        if BASE_SCORE + added_weight >= minimum:
            break
        if cond["signal"]["name"] in disqualifiers:
            continue  # would disqualify the very pattern being probed
        add(cond)
        added_weight += cond["weight"]
        used.append(f"{cond.get('id')}(+{cond['weight']:g})")

    available = sum(c["weight"] for c in supporting if c["signal"]["name"] not in disqualifiers)
    report = {
        "pattern_id": pattern["id"],
        "minimum_score": minimum,
        "projected_score": min(100, BASE_SCORE + added_weight),
        "supporting_added": used,
        "supporting_weight_added": added_weight,
        "supporting_weight_available": available,
        "threshold_reachable": BASE_SCORE + min(50, available) >= minimum,
        "notes": notes,
        "undrivable": undrivable,
    }
    metadata = _metadata_for(pattern)
    if metadata_overrides:
        metadata.update(metadata_overrides)
        report["metadata_overrides"] = dict(metadata_overrides)
    project = {
        "fingerprint_status": "COMPLETE",
        "analysis_capabilities": _capabilities_for(pattern),
        "metadata": metadata,
        "signals_by_name": signals,
    }
    return project, report


# ---------- probing ----------


def probe(
    pattern_id: str,
    patterns: list[dict],
    config: dict,
    entries: dict[str, dict],
    metadata_overrides: dict | None = None,
) -> dict:
    """Builds a project that should match `pattern_id`, classifies it, and
    explains any non-match rather than reporting a bare False."""
    target = next((p for p in patterns if p["id"] == pattern_id), None)
    if target is None:
        raise LookupError(f"no active pattern '{pattern_id}' in the catalog")

    project, build_report = build_project(target, entries, metadata_overrides)
    result = classify.classify_project(project, patterns, config)
    match = next((m for m in result["matches"] if m["pattern"]["id"] == pattern_id), None)

    diagnosis = None
    if match is None:
        diagnosis = "not evaluated at all — check scope, rules_status and eligibility.fingerprintStatuses"
    elif not match["matched"]:
        outcome = match["outcome"]
        if outcome.disqualified:
            cause = next((r for r in outcome.failed_rules if r.get("is_disqualifying")), None)
            diagnosis = (
                f"disqualified at the '{outcome.disqualifying_group}' group"
                + (f" by rule '{cause['rule_id']}'" if cause else "")
            )
        elif match["score"] < target["thresholds"]["minimumScore"]:
            # The failure mode this module exists to name explicitly.
            diagnosis = (
                f"INSUFFICIENT SUPPORTING WEIGHT, not a rule failure: every required condition passed, "
                f"but score {match['score']} < minimumScore {target['thresholds']['minimumScore']}. "
                f"Supporting weight available {build_report['supporting_weight_available']:g}, "
                f"added {build_report['supporting_weight_added']:g}. "
                + (
                    "The pattern cannot reach its own threshold from supporting evidence alone — that is a "
                    "catalog problem, not a probe problem."
                    if not build_report["threshold_reachable"]
                    else "The probe under-supplied supporting signals."
                )
            )
    elif match["role_excluded"]:
        diagnosis = f"role-excluded: project_role {result['project_role']} is in eligibility.excludedProjectRoles"
    elif match["required_capability_missing"]:
        diagnosis = "a required analysis capability was unavailable"

    return {
        "pattern_id": pattern_id,
        "build": build_report,
        "classification_status": result["classification_status"],
        "project_role": result["project_role"],
        "primary_pattern_id": result["primary_pattern_id"],
        "target_matched": bool(match and match["matched"]),
        "target_score": match["score"] if match else None,
        "diagnosis": diagnosis,
        "also_matched": sorted(
            m["pattern"]["id"] for m in result["matches"] if m["matched"] and m["pattern"]["id"] != pattern_id
        ),
        "warnings": result["warnings"],
    }


# Step 2's frameworkFamily enum (steps/step-002-solution-discovery/
# discovery/framework.py FAMILY_RANK), minus 'unknown'.
FRAMEWORK_FAMILIES = ["net-framework", "net-core", "net-standard", "net"]


def audit_one_directional_exclusions(patterns: list[dict], config: dict, entries: dict[str, dict]) -> list[dict]:
    """Part C's mutual-exclusion rule, checked by construction: probe each
    active PRIMARY pattern and report any *other* pattern that also matched
    its canonical project. A co-matcher means the exclusion between the two
    is one-directional (or absent) — relying on score order is not
    separation.

    **The family axis is swept deliberately.** A pattern that declares no
    `frameworkFamily` condition is claiming to be family-agnostic, so its
    canonical project is probed once per family value. Without this the audit
    is blind to the exact bug it exists to catch: probing with
    `frameworkFamily: None` accidentally shields the project from
    family-bound poachers like fx47-class-library, which requires
    `net-framework` — and that combination (ASP.NET Core hosting signals on
    a .NET Framework TFM) is precisely the real case that was missed.
    """
    findings = []
    for pattern in sorted(patterns, key=lambda p: p["id"]):
        if pattern["classification_role"] != "PRIMARY" or pattern["rules_status"] != "active":
            continue
        metadata_conds = pattern["detection_rules"].get("metadata") or []
        declares_family = any(c["field"] == "frameworkFamily" for c in metadata_conds)
        # A pattern pinned to a structuralType is not claiming
        # family-agnosticism — its project type decides what framework it can
        # even have. Sweeping families for ssis-package invents a .dtproj with
        # a TargetFramework, which step 2 can never produce (framework_family
        # is null for one), and every "finding" from it is a sweep artifact.
        pins_structural_type = any(c["field"] == "structuralType" for c in metadata_conds)
        if declares_family or pins_structural_type:
            sweep: list[dict | None] = [None]
        else:
            sweep = [{"frameworkFamily": fam, "frameworkVersion": "1.0"} for fam in FRAMEWORK_FAMILIES]
        for overrides in sweep:
            result = probe(pattern["id"], patterns, config, entries, overrides)
            if result["also_matched"] or not result["target_matched"]:
                findings.append(result)
    return findings


def main() -> int:
    patterns = load_catalog()
    config = _latest_config()
    _version, entries = registry.load_active_registry_entries(PLATFORM_ROOT)

    if "--audit" in sys.argv:
        findings = audit_one_directional_exclusions(patterns, config, entries)
        if not findings:
            print("No one-directional exclusions found: every active PRIMARY pattern's canonical project "
                  "matched that pattern and nothing else.")
            return 0
        for f in findings:
            probed_as = f["build"].get("metadata_overrides")
            suffix = f" [probed as frameworkFamily={probed_as['frameworkFamily']}]" if probed_as else ""
            print(f"\n{f['pattern_id']}{suffix}  (score {f['target_score']}, status {f['classification_status']})")
            if not f["target_matched"]:
                print(f"  DID NOT MATCH ITS OWN PROBE: {f['diagnosis']}")
            for other in f["also_matched"]:
                print(f"  also matched: {other}")
            if f["build"]["undrivable"]:
                for u in f["build"]["undrivable"]:
                    print(f"  probe limitation: {u}")
        print(f"\n{len(findings)} pattern(s) with findings.")
        return 1

    targets = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not targets:
        print(__doc__)
        return 2
    for pattern_id in targets:
        print(json.dumps(probe(pattern_id, patterns, config, entries), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
