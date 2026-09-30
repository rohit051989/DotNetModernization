"""--corpus mode — 26-STEP-005-PATTERN-DISCOVERY.md Part H.

With current samples step 5 finds almost nothing: eShopModernizing has
zero unmatched projects and eShopOnWeb has three single-project shapes.
**Synthetic fixtures are the only real test until a client estate
exists**, so they carry more weight here than in previous steps — which
is why this runs the clustering engine directly against frozen project
fixtures rather than against the database.
"""

import json
from pathlib import Path

import main as step
from engine import cluster as cluster_engine
from engine import coverage as coverage_engine
from engine import signature as sig


def _projects_from_fixture(fixture: dict, config: dict) -> list[dict]:
    projects = []
    for p in fixture["projects"]:
        if p["classification_status"] not in cluster_engine.ELIGIBLE_STATUSES:
            continue
        signal_rows = [{"signal_name": n, "extraction_confidence": c} for n, c in p["signals"].items()]
        projects.append(
            {
                "project_id": p["project_id"],
                "repository_id": p["repository_id"],
                "repository_slug": p["repository_slug"],
                "project_path": p["project_path"],
                "classification_status": p["classification_status"],
                "classification_step_execution_id": p.get("classification_step_execution_id"),
                "signal_set": set(sig.core_signature(signal_rows, config["min_signal_confidence"])),
                "facets": {f: p["facets"].get(f) for f in sig.FACET_FIELDS},
            }
        )
    return projects


def _summary(fixture: dict, clusters: list[dict], config: dict) -> dict:
    eligible = _projects_from_fixture(fixture, config)
    clustered = [c for c in clusters if not c["is_singleton"]]
    singletons = [c for c in clusters if c["is_singleton"]]
    breakdown: dict[str, int] = {}
    for p in fixture["projects"]:
        breakdown[p["classification_status"]] = breakdown.get(p["classification_status"], 0) + 1
    return {
        "cluster_count": len(clustered),
        "singleton_count": len(singletons),
        "projects_eligible": len(eligible),
        "largest_cluster_size": max((c["member_count"] for c in clustered), default=0),
        "excluded_insufficient_fingerprint": breakdown.get("INSUFFICIENT_FINGERPRINT", 0),
        "clusters": [
            {
                "cluster_id": c["cluster_id"],
                "cluster_method": c["cluster_method"],
                "member_count": c["member_count"],
                "repository_count": c["repository_count"],
                "repository_distribution": c["repository_distribution"],
                "cohesion": c["cohesion"],
                "is_singleton": c["is_singleton"],
                "signals": c["canonical_signature"]["signals"],
                "similar_patterns": c.get("similar_patterns") or [],
                "member_paths": [m["project_path"] for m in c["members"]],
            }
            for c in clusters
        ],
    }


def _evaluate(fixture: dict) -> dict:
    _version, config = step.latest_config()
    config = {**config, **(fixture.get("config_overrides") or {})}
    projects = _projects_from_fixture(fixture, config)
    clusters = cluster_engine.build_clusters(projects, config)
    pattern_sets = {pid: set(names) for pid, names in (fixture.get("catalog_patterns") or {}).items()}
    cluster_engine.pattern_proximity(clusters, pattern_sets, config)
    return _summary(fixture, clusters, config)


def _diff(expected: dict, actual: dict) -> list[str]:
    findings = []
    for field in ("cluster_count", "singleton_count", "projects_eligible", "largest_cluster_size",
                  "excluded_insufficient_fingerprint"):
        if expected[field] != actual[field]:
            findings.append(f"{field}: {expected[field]} -> {actual[field]}")
    exp_by_id = {c["cluster_id"]: c for c in expected["clusters"]}
    act_by_id = {c["cluster_id"]: c for c in actual["clusters"]}
    for cid in sorted(set(exp_by_id) | set(act_by_id)):
        if cid not in exp_by_id:
            findings.append(f"new cluster {cid}: {act_by_id[cid]['member_paths']}")
        elif cid not in act_by_id:
            findings.append(f"cluster {cid} disappeared: {exp_by_id[cid]['member_paths']}")
        elif exp_by_id[cid] != act_by_id[cid]:
            was, now = exp_by_id[cid], act_by_id[cid]
            for k in sorted(set(was) | set(now)):
                if was.get(k) != now.get(k):
                    findings.append(f"cluster {cid} {k}: {was.get(k)} -> {now.get(k)}")
    return findings


def _determinism_checks() -> list[str]:
    """Part H: two runs, identical checksum and identical cluster_ids.

    Also the Part A2 / Part E assertion this step exists to protect —
    the clusters artifact must be byte-identical with narration on and
    off. Narration is not an input to build_clusters_artifact, and this
    proves it stays that way.
    """
    findings = []
    fixture_path = Path(__file__).resolve().parent / "corpus" / "fixtures" / "cross-repository-exact.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    _version, base_config = step.latest_config()

    def artifact_bytes(enable_narration: bool) -> bytes:
        config = {**base_config, "enable_narration": enable_narration}
        projects = _projects_from_fixture(fixture, config)
        clusters = cluster_engine.build_clusters(projects, config)
        cluster_engine.pattern_proximity(clusters, {}, config)
        for c in clusters:
            c["needs_rereview"], c["rereview_reason"] = False, None
        summary = {
            "coverage": coverage_engine.build_coverage(2, 2),
            "projects_total": len(fixture["projects"]),
            "projects_eligible": len(projects),
            "projects_clustered": sum(c["member_count"] for c in clusters if not c["is_singleton"]),
            "projects_singleton": sum(1 for c in clusters if c["is_singleton"]),
            "cluster_count": sum(1 for c in clusters if not c["is_singleton"]),
            "singleton_count": sum(1 for c in clusters if c["is_singleton"]),
            "largest_cluster_size": max((c["member_count"] for c in clusters if not c["is_singleton"]), default=0),
            "stale_cluster_count": 0,
            "needs_rereview_count": 0,
            "eligibility_breakdown": {"NO_PATTERN_MATCHED": len(projects)},
            "excluded_insufficient_fingerprint": 0,
        }
        return step.serialise(step.build_clusters_artifact("corpus", clusters, summary, config))

    first, second = artifact_bytes(False), artifact_bytes(False)
    if first != second:
        findings.append("two runs with narration OFF produced different bytes")

    narration_on = artifact_bytes(True)
    if first != narration_on:
        findings.append("clusters artifact differs between narration ON and OFF — narration reached the deterministic artifact")
    return findings


def _rereview_checks() -> list[str]:
    """Part D "Decision context and re-review". Table-driven because the
    interesting behaviour is entirely in the boundaries — the multiplier
    handles clusters that were already substantial, the floor handles the
    ones that were not, and each is wrong without the other.
    """
    min_members = 5
    cases = [
        # (label, existing, member_count, expect_flag)
        ("undecided cluster is never re-reviewed",
         {"status": "candidate", "decided_at_member_count": 2, "decided_at_coverage": 0.2}, 99, False),
        ("rejected at 2, now 9 -> fires (2*3=6, floor 5, max 6)",
         {"status": "rejected", "decided_at_member_count": 2, "decided_at_coverage": 0.21}, 9, True),
        ("rejected at 2, now 6 -> does not fire (not > 6)",
         {"status": "rejected", "decided_at_member_count": 2, "decided_at_coverage": 0.21}, 6, False),
        ("singleton rejected at 1, now 4 -> floor suppresses it",
         {"status": "rejected", "decided_at_member_count": 1, "decided_at_coverage": 0.3}, 4, False),
        ("singleton rejected at 1, now 6 -> clears the floor",
         {"status": "rejected", "decided_at_member_count": 1, "decided_at_coverage": 0.3}, 6, True),
        ("validated_new at 10, now 25 -> multiplier governs, not the floor",
         {"status": "validated_new", "decided_at_member_count": 10, "decided_at_coverage": 0.9}, 25, False),
        ("validated_new at 10, now 31 -> fires",
         {"status": "validated_new", "decided_at_member_count": 10, "decided_at_coverage": 0.9}, 31, True),
        ("never clustered before -> nothing to revisit", None, 50, False),
    ]
    findings = []
    for label, existing, member_count, expected in cases:
        flag, reason = coverage_engine.rereview_decision(existing, member_count, 0.68, min_members)
        if flag is not expected:
            findings.append(f"{label}: expected {expected}, got {flag}")
        elif flag and not reason:
            findings.append(f"{label}: flagged without a reason")

    # A flag an earlier run raised survives a run where membership dipped
    # back under the threshold — shrinking does not un-ask the question,
    # and dropping it silently would lose a queued review.
    held, reason = coverage_engine.rereview_decision(
        {"status": "rejected", "decided_at_member_count": 2, "decided_at_coverage": 0.2,
         "needs_rereview": True, "rereview_reason": "raised earlier"},
        3, 0.68, min_members,
    )
    if not held or reason != "raised earlier":
        findings.append("an already-raised needs_rereview flag was dropped when membership dipped")

    # Coverage is reported, not used as a gate: a decision made at low
    # coverage is not re-asked merely because coverage improved. Only
    # member growth triggers.
    flag, _ = coverage_engine.rereview_decision(
        {"status": "rejected", "decided_at_member_count": 4, "decided_at_coverage": 0.1}, 4, 1.0, min_members
    )
    if flag:
        findings.append("coverage improvement alone triggered re-review; only member growth should")
    return findings


def run(corpus_dir: Path) -> int:
    fixtures_dir, expected_dir = corpus_dir / "fixtures", corpus_dir / "expected"
    total = changed = 0
    for fixture_path in sorted(fixtures_dir.glob("*.json")):
        total += 1
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        actual = _evaluate(fixture)
        expected_path = expected_dir / fixture_path.name
        if not expected_path.exists():
            print(f"NEW      {fixture_path.stem}: no expected file — run with --write-expected to seed it")
            continue
        findings = _diff(json.loads(expected_path.read_text(encoding="utf-8")), actual)
        if findings:
            changed += 1
            print(f"CHANGED  {fixture_path.stem}:")
            for f in findings:
                print(f"  - {f}")
        else:
            print(f"OK       {fixture_path.stem}: {actual['cluster_count']} cluster(s), {actual['singleton_count']} singleton(s)")

    print()
    determinism = _determinism_checks()
    for finding in determinism:
        changed += 1
        print(f"CHANGED  determinism: {finding}")
    if not determinism:
        print("OK       determinism: two runs identical; narration ON and OFF byte-identical")

    rereview = _rereview_checks()
    for finding in rereview:
        changed += 1
        print(f"CHANGED  rereview: {finding}")
    if not rereview:
        print("OK       rereview: multiplier, floor, persistence and coverage-independence all hold")

    print(f"\n{total} fixture(s), {changed} changed.")
    return 1 if changed else 0


def write_expected(corpus_dir: Path) -> None:
    fixtures_dir, expected_dir = corpus_dir / "fixtures", corpus_dir / "expected"
    expected_dir.mkdir(parents=True, exist_ok=True)
    for fixture_path in sorted(fixtures_dir.glob("*.json")):
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        out = expected_dir / fixture_path.name
        out.write_text(json.dumps(_evaluate(fixture), sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}")
