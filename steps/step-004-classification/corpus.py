"""--corpus mode — 24-STEP-004-CLASSIFICATION.md Part H. Runs the current
catalog (read live from the database — a rule edit needs no rescan to take
effect) against frozen fingerprint fixtures, and diffs against recorded
expectations, ignoring volatile fields.
"""

import json
import os
from pathlib import Path

import db
from engine import classify, coverage, registry

SCORE_TOLERANCE = 2


def _database_url() -> str:
    """Single-machine setup (CLAUDE.md): one Postgres instance, shared with
    the backend. Corpus mode has no StepContext to hand it a database_url,
    so it reads the same .env the backend does."""
    if "DATABASE_URL" in os.environ:
        return os.environ["DATABASE_URL"]
    env_path = Path(__file__).resolve().parents[2] / "backend" / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError(f"DATABASE_URL not set and not found in {env_path}")


def _pattern_for_engine(row: dict) -> dict:
    return {
        "id": row["id"],
        "version": row["version"],
        "classification_role": row["classification_role"],
        "classification_family": row["classification_family"],
        "classification_value": row["classification_value"],
        "scope": row["scope"],
        "priority": row["priority"],
        "compatible_with": row["compatible_with"] or [],
        "conflicts_with": row["conflicts_with"] or [],
        "anchor_signals": row["anchor_signals"] or [],
        "eligibility": row["eligibility"],
        "analysis_requirements": row["analysis_requirements"],
        "thresholds": row["thresholds"],
        "rules_status": row["rules_status"],
        "required_signals_pending": row["required_signals_pending"] or [],
        "detection_rules": row["detection_rules"],
    }


def _latest_config(config_dir: Path) -> dict:
    candidates = sorted(config_dir.glob("classification-config-*.json"))
    return json.loads(candidates[-1].read_text(encoding="utf-8"))


def _actual_summary(result: dict) -> dict:
    """The comparison-relevant projection of a classify_project() result —
    already free of catalog_revision/config_version/timestamps, since
    classify_project() never produces those (main.py attaches them
    separately, for exactly this reason)."""
    return {
        "classification_status": result["classification_status"],
        "project_role": result["project_role"],
        "primary_pattern_id": result["primary_pattern_id"],
        "matched_pattern_ids": sorted(m["pattern"]["id"] for m in result["matches"] if m["matched"]),
        "scores": {m["pattern"]["id"]: m["score"] for m in result["matches"]},
        # Why each non-matching pattern failed, by rule id — the
        # `is_disqualifying` half of failed_rules only (Part F). Pins the
        # flag, and pins the ordering: these come from the front of
        # failed_rules, where the sort puts genuine causes. Unsatisfied
        # alternatives inside groups that passed are deliberately excluded —
        # they are tuning context and would make this churn on every rule
        # edit.
        #
        # Note the coverage limit: a pattern disqualified by a `none`
        # condition records its cause in negative_triggered, leaving
        # failed_rules empty, so it does not appear here at all. Those
        # exclusions are pinned indirectly, via matched_pattern_ids.
        "disqualifying_rules": {
            m["pattern"]["id"]: [r["rule_id"] for r in m["outcome"].failed_rules if r.get("is_disqualifying")]
            for m in result["matches"]
            if any(r.get("is_disqualifying") for r in m["outcome"].failed_rules)
        },
    }


def _diff(expected: dict, actual: dict) -> list[str]:
    findings = []
    if expected["classification_status"] != actual["classification_status"]:
        findings.append(f"status changed: {expected['classification_status']} -> {actual['classification_status']}")
    if expected["classification_status"] != "AMBIGUOUS" and actual["classification_status"] == "AMBIGUOUS":
        findings.append("newly AMBIGUOUS")
    if expected["classification_status"] not in ("NO_PATTERN_MATCHED",) and actual["classification_status"] == "NO_PATTERN_MATCHED":
        findings.append("newly NO_PATTERN_MATCHED")
    if expected["project_role"] != actual["project_role"]:
        findings.append(f"project_role changed: {expected['project_role']} -> {actual['project_role']}")
    if expected["primary_pattern_id"] != actual["primary_pattern_id"]:
        findings.append(f"primary_pattern_id changed: {expected['primary_pattern_id']} -> {actual['primary_pattern_id']}")
    if set(expected["matched_pattern_ids"]) != set(actual["matched_pattern_ids"]):
        findings.append(
            f"matched pattern set changed: {expected['matched_pattern_ids']} -> {actual['matched_pattern_ids']}"
        )
    for pattern_id, expected_score in expected["scores"].items():
        actual_score = actual["scores"].get(pattern_id)
        if actual_score is None:
            continue
        if abs(actual_score - expected_score) > SCORE_TOLERANCE:
            findings.append(f"{pattern_id} score delta beyond tolerance: {expected_score} -> {actual_score}")

    # Why a pattern failed is part of the contract, not just whether it did:
    # a rule edit that changes the disqualifying cause while leaving the
    # status intact is exactly the kind of drift this corpus exists to catch.
    # Absent in a pre-extension baseline, so treat missing as "not asserted".
    expected_rules = expected.get("disqualifying_rules")
    if expected_rules is not None:
        actual_rules = actual["disqualifying_rules"]
        for pattern_id in sorted(set(expected_rules) | set(actual_rules)):
            was = expected_rules.get(pattern_id, [])
            now = actual_rules.get(pattern_id, [])
            if was != now:
                findings.append(f"{pattern_id} disqualifying rules changed: {was} -> {now}")
    return findings


def _coverage_summary(patterns: list[dict], project_results: list[dict]) -> dict:
    """The repo-level half of the contract. Per-project expectations cannot
    pin section 18's `most_frequent_unmatched_signal_combinations` — it is a
    property of the repository as a whole, and the thing step 5 clusters on.

    Only that field is asserted. The rest of the coverage report (registered
    and referenced signal counts, active_pattern_count,
    never_matched_pattern_ids) is a property of the whole catalog rather than
    of these fixtures, so pinning it here would fail on every unrelated
    pattern edit.
    """
    report = coverage.build_coverage_report(
        patterns=patterns,
        project_results=project_results,
        registered_signal_names=frozenset(),
        catalog_version="corpus",
        catalog_revision=0,
        signal_registry_version=None,
    )
    return {
        "most_frequent_unmatched_signal_combinations": report[
            "most_frequent_unmatched_signal_combinations"
        ],
    }


def _diff_coverage(expected: dict, actual: dict) -> list[str]:
    key = "most_frequent_unmatched_signal_combinations"
    was, now = expected[key], actual[key]
    if was == now:
        return []
    return [f"{key} changed: expected {json.dumps(was)}, actual {json.dumps(now)}"]


def run(corpus_dir: Path, platform_root: Path) -> int:
    config = _latest_config(platform_root / "steps" / "step-004-classification" / "config")
    _registry_version, _registered = registry.load_active_registry(platform_root)

    with db.connect(_database_url()) as conn:
        pattern_rows = db.load_active_catalog(conn)
    patterns = [_pattern_for_engine(r) for r in pattern_rows]

    fingerprints_dir = corpus_dir / "fingerprints"
    expected_dir = corpus_dir / "expected"

    total = 0
    changed = 0
    for repo_dir in sorted(fingerprints_dir.iterdir()):
        if not repo_dir.is_dir():
            continue
        repo_results = []
        for fixture_path in sorted(repo_dir.glob("*.json")):
            total += 1
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
            signals_by_name: dict[str, list[dict]] = {}
            for s in fixture["signals"]:
                signals_by_name.setdefault(s["signal_name"], []).append(s)
            project_input = {
                "fingerprint_status": fixture["fingerprint_status"],
                "analysis_capabilities": fixture["analysis_capabilities"],
                "metadata": fixture["metadata"],
                "signals_by_name": signals_by_name,
            }
            result = classify.classify_project(project_input, patterns, config)
            repo_results.append(result)
            actual = _actual_summary(result)

            expected_path = expected_dir / repo_dir.name / fixture_path.name
            if not expected_path.exists():
                print(f"NEW      {repo_dir.name}/{fixture_path.stem}: no expected file — run with --write-expected to seed it")
                continue
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            findings = _diff(expected, actual)
            if findings:
                changed += 1
                print(f"CHANGED  {repo_dir.name}/{fixture_path.stem}:")
                for f in findings:
                    print(f"  - {f}")
            else:
                print(f"OK       {repo_dir.name}/{fixture_path.stem}: {actual['classification_status']}")

        coverage_path = expected_dir / repo_dir.name / "_coverage.json"
        if repo_results and coverage_path.exists():
            findings = _diff_coverage(
                json.loads(coverage_path.read_text(encoding="utf-8")),
                _coverage_summary(patterns, repo_results),
            )
            if findings:
                changed += 1
                print(f"CHANGED  {repo_dir.name}/_coverage:")
                for f in findings:
                    print(f"  - {f}")
            else:
                print(f"OK       {repo_dir.name}/_coverage")

    print(f"\n{total} project(s), {changed} changed beyond tolerance.")
    return 1 if changed else 0


def write_expected(corpus_dir: Path, platform_root: Path) -> None:
    """Seeds/refreshes corpus/expected/ from the current catalog + fixtures —
    used once to establish the baseline, not part of normal --corpus runs."""
    config = _latest_config(platform_root / "steps" / "step-004-classification" / "config")
    with db.connect(_database_url()) as conn:
        pattern_rows = db.load_active_catalog(conn)
    patterns = [_pattern_for_engine(r) for r in pattern_rows]

    fingerprints_dir = corpus_dir / "fingerprints"
    expected_dir = corpus_dir / "expected"
    for repo_dir in sorted(fingerprints_dir.iterdir()):
        if not repo_dir.is_dir():
            continue
        out_dir = expected_dir / repo_dir.name
        out_dir.mkdir(parents=True, exist_ok=True)
        repo_results = []
        for fixture_path in sorted(repo_dir.glob("*.json")):
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
            signals_by_name: dict[str, list[dict]] = {}
            for s in fixture["signals"]:
                signals_by_name.setdefault(s["signal_name"], []).append(s)
            project_input = {
                "fingerprint_status": fixture["fingerprint_status"],
                "analysis_capabilities": fixture["analysis_capabilities"],
                "metadata": fixture["metadata"],
                "signals_by_name": signals_by_name,
            }
            result = classify.classify_project(project_input, patterns, config)
            repo_results.append(result)
            summary = _actual_summary(result)
            out_path = out_dir / fixture_path.name
            out_path.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {out_path}")
        if repo_results:
            out_path = out_dir / "_coverage.json"
            out_path.write_text(
                json.dumps(_coverage_summary(patterns, repo_results), sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"wrote {out_path}")


if __name__ == "__main__":
    import sys

    _platform_root = Path(__file__).resolve().parents[2]
    _corpus_dir = Path(__file__).resolve().parent / "corpus"
    if "--write-expected" in sys.argv:
        write_expected(_corpus_dir, _platform_root)
    else:
        sys.exit(run(_corpus_dir, _platform_root))
