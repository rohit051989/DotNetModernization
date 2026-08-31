#!/usr/bin/env python
"""Step 4 — pattern classification against catalog.

Invocation (process adapter, see docs/11-STEP-CONTRACT.md): StepContext JSON
arrives on stdin, StepResult JSON is written to stdout, log lines go to
stderr.

    Get-Content sample-context.json | .venv/Scripts/python.exe main.py

Regression corpus mode (docs/24-STEP-004-CLASSIFICATION.md Part H) runs
against frozen fingerprint fixtures instead of the database and diffs
against recorded expectations, ignoring volatile fields:

    .venv/Scripts/python.exe main.py --corpus
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import db
from engine import classify, coverage, registry

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
STEP_DIR = Path(__file__).resolve().parent
CONFIG_DIR = STEP_DIR / "config"
CORPUS_DIR = STEP_DIR / "corpus"

ARTIFACT_TYPE = "application-classification"
ARTIFACT_VERSION = "1.0.0"
CATALOG_VERSION = "2.0"  # mirrors backend/app/routers/catalog.py's CATALOG_VERSION


def _latest_config() -> tuple[str, dict]:
    candidates = sorted(CONFIG_DIR.glob("classification-config-*.json"))
    if not candidates:
        raise FileNotFoundError(f"No classification-config-*.json found under {CONFIG_DIR}")
    path = candidates[-1]
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["config_version"], data


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


def _explain(pattern: dict, m: dict) -> str:
    name = pattern["name"] if "name" in pattern else pattern["id"]
    if m["matched"]:
        primary = [r["signal_name"] for r in m["outcome"].matched_rules if "signal_name" in r]
        evidence = ", ".join(primary) if primary else "metadata conditions"
        return f"Matched {name} on {evidence}."
    if m["role_excluded"]:
        return f"Not evaluated as primary: project role excludes {name}."
    if m["required_capability_missing"]:
        return f"Not matched: a required analysis capability for {name} was unavailable."
    if m["outcome"].disqualified:
        return f"Not matched: disqualified at the '{m['outcome'].disqualifying_group}' stage for {name}."
    return f"Not matched: scored {m['score']}, below the minimumScore threshold for {name}."


def _project_artifact(project_id: str, project_path: str, result: dict) -> dict:
    matches_payload = []
    for m in result["matches"]:
        pattern = m["pattern"]
        matches_payload.append(
            {
                "pattern_id": pattern["id"],
                "pattern_version": pattern["version"],
                "classification_role": pattern["classification_role"],
                "classification_family": pattern["classification_family"],
                "classification_value": pattern["classification_value"],
                "matched": m["matched"],
                "match_score": m["score"],
                "confidence": round(m["confidence"], 2),
                "confidence_level": m["confidence_level"],
                "is_primary_selected": m["is_primary_selected"],
                "rejection_reason": m["rejection_reason"],
                "role_excluded": m["role_excluded"],
                "required_capability_missing": m["required_capability_missing"],
                "matched_rules": m["outcome"].matched_rules + m["outcome"].supporting_matched,
                "failed_rules": m["outcome"].failed_rules,
                "negative_triggered": m["outcome"].negative_triggered,
                "explanation": _explain(pattern, m),
            }
        )
    matches_payload.sort(key=lambda x: x["pattern_id"])

    role_confidence = result["project_role_confidence"]
    return {
        "project_id": project_id,
        "project_path": project_path,
        "classification_status": result["classification_status"],
        "project_role": result["project_role"],
        "project_role_confidence": round(role_confidence, 2) if role_confidence is not None else None,
        "evaluated_pattern_count": result["evaluated_pattern_count"],
        "primary_pattern_id": result["primary_pattern_id"],
        "matches": matches_payload,
        "warnings": result["warnings"],
    }


def run_for_repository(database_url: str, repository_id: str, output_dir: Path, step_execution_id: str | None) -> dict:
    config_version, config = _latest_config()

    with db.connect(database_url) as conn:
        repository_row = db.load_repository(conn, repository_id)
        catalog_revision = db.current_catalog_revision(conn)
        signal_registry_ver = db.signal_registry_version(conn, repository_id)
        registry_version, registered_names = registry.load_active_registry(PLATFORM_ROOT)

        pattern_rows = db.load_active_catalog(conn)
        patterns = [_pattern_for_engine(r) for r in pattern_rows]
        project_rows = db.load_projects_for_repository(conn, repository_id)

        project_artifacts = []
        engine_results = []
        for project_row in project_rows:
            signals_by_name = db.load_signals_for_project(conn, str(project_row["id"]))
            metadata = db.project_metadata(project_row)
            project_input = {
                "fingerprint_status": project_row["fingerprint_status"],
                "analysis_capabilities": project_row["analysis_capabilities"] or {},
                "metadata": metadata,
                "signals_by_name": signals_by_name,
            }
            result = classify.classify_project(project_input, patterns, config)
            project_artifacts.append(_project_artifact(str(project_row["id"]), project_row["relative_path"], result))
            engine_results.append({"project_row": project_row, "result": result})

        coverage_report = coverage.build_coverage_report(
            patterns, [r["result"] for r in engine_results], registered_names,
            CATALOG_VERSION, catalog_revision, signal_registry_ver,
        )

        db_project_results = []
        for item in engine_results:
            project_row, result = item["project_row"], item["result"]
            db_matches = []
            for m in result["matches"]:
                pattern = m["pattern"]
                db_matches.append(
                    {
                        "pattern_id": pattern["id"],
                        "pattern_version": pattern["version"],
                        "matched": m["matched"],
                        "classification_role": pattern["classification_role"],
                        "match_score": m["score"],
                        "confidence": round(m["confidence"], 2),
                        "confidence_level": m["confidence_level"],
                        "is_primary_selected": m["is_primary_selected"],
                        "rejection_reason": m["rejection_reason"],
                        "engagement_scope_status": None,
                        "matched_rules": m["outcome"].matched_rules + m["outcome"].supporting_matched,
                        "failed_rules": m["outcome"].failed_rules,
                        "missing_preferred": [],
                        "negative_triggered": m["outcome"].negative_triggered,
                        "explanation": _explain(pattern, m),
                    }
                )
            db_project_results.append(
                {
                    "project_id": str(project_row["id"]),
                    "classification_status": result["classification_status"],
                    "project_role": result["project_role"],
                    "project_role_confidence": result["project_role_confidence"],
                    "catalog_revision": catalog_revision,
                    "signal_registry_version": signal_registry_ver,
                    "config_version": config_version,
                    "evaluated_pattern_count": result["evaluated_pattern_count"],
                    "primary_pattern_id": result["primary_pattern_id"],
                    "warnings": result["warnings"],
                    "step_execution_id": step_execution_id,
                    "matches": db_matches,
                }
            )

        db.replace_classification_results(
            conn, repository_id, db_project_results,
            {**coverage_report, "step_execution_id": step_execution_id},
        )

    repository_slug = repository_row["name"].lower().replace(" ", "-") if repository_row else repository_id
    artifact = {
        "artifact_type": ARTIFACT_TYPE,
        "artifact_version": ARTIFACT_VERSION,
        "repository_id": repository_id,
        "repository_slug": repository_slug,
        "catalog_version": CATALOG_VERSION,
        "signal_registry_version": signal_registry_ver,
        "projects": sorted(project_artifacts, key=lambda p: p["project_path"]),
        "governance_summary": coverage_report,
        "warnings": [],
    }

    body = json.dumps(artifact, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    body_bytes = body.encode("utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / "application-classification.json"
    # write_bytes, not write_text: text mode on Windows translates \n -> \r\n,
    # which would make the on-disk file's bytes disagree with the checksum
    # computed from the in-memory string below.
    artifact_path.write_bytes(body_bytes)
    checksum = "sha256:" + hashlib.sha256(body_bytes).hexdigest()

    return {
        "artifact_path": artifact_path,
        "checksum": checksum,
        "project_count": len(project_artifacts),
        "catalog_revision": catalog_revision,
        "config_version": config_version,
        "signal_registry_version": signal_registry_ver,
    }


def _run_process_adapter() -> None:
    context = json.loads(sys.stdin.read())
    repository_id = context["parameters"]["repository_id"]
    output_dir = Path(context["output_dir"])

    try:
        outcome = run_for_repository(
            context["database_url"], repository_id, output_dir, context.get("step_execution_id")
        )
    except Exception as exc:  # noqa: BLE001 - step contract requires FAILED, never a crash with no result
        result = {
            "envelope_version": "1.0",
            "exit_status": "FAILED",
            "exit_message": f"{type(exc).__name__}: {exc}",
        }
        print(json.dumps(result))
        return

    result = {
        "envelope_version": "1.0",
        "exit_status": "COMPLETED",
        "exit_message": f"Classified {outcome['project_count']} project(s) against catalog revision {outcome['catalog_revision']}.",
        "metrics": {
            "read_count": outcome["project_count"],
            "write_count": outcome["project_count"],
            "skip_count": 0,
            "commit_count": 1,
        },
        "outputs": [
            {
                "artifact_type": ARTIFACT_TYPE,
                "artifact_version": ARTIFACT_VERSION,
                "uri": f"file:///{outcome['artifact_path'].as_posix()}",
                "checksum": outcome["checksum"],
                "metadata": {
                    "catalog_revision": outcome["catalog_revision"],
                    "config_version": outcome["config_version"],
                    "signal_registry_version": outcome["signal_registry_version"],
                    "project_count": outcome["project_count"],
                },
            }
        ],
    }
    print(json.dumps(result))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", action="store_true", help="Run in regression-corpus mode; see corpus.py.")
    args = parser.parse_args()

    if args.corpus:
        import corpus as corpus_mode

        sys.exit(corpus_mode.run(CORPUS_DIR, PLATFORM_ROOT))

    _run_process_adapter()


if __name__ == "__main__":
    main()
