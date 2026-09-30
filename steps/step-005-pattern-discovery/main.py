#!/usr/bin/env python
"""Step 5 — pattern discovery clustering for unmatched applications.

Invocation (process adapter, docs/11-STEP-CONTRACT.md): StepContext JSON
on stdin, StepResult JSON on stdout, logs on stderr.

    Get-Content sample-context.json | .venv/Scripts/python.exe main.py

Regression corpus mode (26-STEP-005-PATTERN-DISCOVERY.md Part H):

    .venv/Scripts/python.exe main.py --corpus
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import db
from engine import cluster as cluster_engine
from engine import coverage as coverage_engine
from engine import narration as narration_engine
from engine import signature as sig

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
STEP_DIR = Path(__file__).resolve().parent
CONFIG_DIR = STEP_DIR / "config"
CORPUS_DIR = STEP_DIR / "corpus"

ARTIFACT_TYPE = "pattern-candidate-clusters"
ARTIFACT_VERSION = "1.0.0"


def latest_config() -> tuple[str, dict]:
    candidates = sorted(CONFIG_DIR.glob("discovery-config-*.json"))
    if not candidates:
        raise FileNotFoundError(f"No discovery-config-*.json found under {CONFIG_DIR}")
    data = json.loads(candidates[-1].read_text(encoding="utf-8"))
    return data["config_version"], data


def _camel(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(word.capitalize() for word in rest)


def _camel_keys(value):
    if isinstance(value, dict):
        return {_camel(k): _camel_keys(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_camel_keys(v) for v in value]
    return value


def build_clusters_artifact(engagement_id: str, clusters: list[dict], summary: dict, config: dict) -> dict:
    """The deterministic artifact. Narration is NOT a parameter here and
    must never become one: Part A2 splits the two artifacts precisely so
    that a non-deterministic name cannot reach a checksum-asserted file.
    """
    return {
        "artifactType": ARTIFACT_TYPE,
        "artifactVersion": ARTIFACT_VERSION,
        "engagementId": engagement_id,
        "config": {
            "clusteringScope": config["clustering_scope"],
            "similarityThreshold": config["similarity_threshold"],
            "minClusterSize": config["min_cluster_size"],
            "facetMode": config["facet_mode"],
            "minSignalConfidence": config["min_signal_confidence"],
            "minRereviewMembers": config["min_rereview_members"],
        },
        # eligibility_breakdown is keyed by classification STATUS VALUES
        # (NO_PATTERN_MATCHED), not by field names, so it is spliced back
        # verbatim after camelising the rest. Camelising it produced
        # "NOPatternMatched", which is neither the status nor a field name.
        "summary": {
            **{k: v for k, v in _camel_keys(summary).items() if k != "eligibilityBreakdown"},
            "eligibilityBreakdown": summary["eligibility_breakdown"],
        },
        "clusters": [
            {
                "clusterId": c["cluster_id"],
                "clusterMethod": c["cluster_method"],
                "canonicalSignature": _camel_keys(c["canonical_signature"]),
                "memberCount": c["member_count"],
                "repositoryCount": c["repository_count"],
                "repositoryDistribution": c["repository_distribution"],
                "cohesion": c["cohesion"],
                "isSingleton": c["is_singleton"],
                "needsRereview": c.get("needs_rereview", False),
                "similarPatterns": [
                    {"patternId": s["pattern_id"], "similarity": s["similarity"]}
                    for s in (c.get("similar_patterns") or [])
                ],
                "members": [
                    {
                        "projectId": str(m["project_id"]),
                        "repositorySlug": m["repository_slug"],
                        "projectPath": m["project_path"],
                        "classificationStatus": m["classification_status"],
                        "similarityToSignature": m["similarity_to_signature"],
                        "signalCount": m["signal_count"],
                        "classificationStepExecutionId": (
                            str(m["classification_step_execution_id"])
                            if m["classification_step_execution_id"]
                            else None
                        ),
                    }
                    for m in c["members"]
                ],
            }
            for c in clusters
        ],
    }


def serialise(artifact: dict) -> bytes:
    return (json.dumps(artifact, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-")


def run_for_engagement(database_url: str, engagement_id: str, output_dir: Path, step_execution_id: str | None) -> dict:
    config_version, config = latest_config()

    with db.connect(database_url) as conn:
        all_repos = db.repositories_in_engagement(conn, engagement_id)
        included_ids = db.repositories_with_classifications(conn, engagement_id)
        coverage = coverage_engine.build_coverage(len(all_repos), len(included_ids))

        if coverage["repositories_included"] == 0:
            pending = ", ".join(r["name"] for r in all_repos) or "none registered"
            return {
                "noop": True,
                "message": f"No repository in '{engagement_id}' has classification results yet. Pending: {pending}.",
                "coverage": coverage,
            }

        rows = db.eligible_projects(conn, engagement_id, cluster_engine.ELIGIBLE_STATUSES)
        signals = db.signals_for_projects(conn, [str(r["project_id"]) for r in rows])

        projects = []
        for row in rows:
            pid = str(row["project_id"])
            names = sig.core_signature(signals.get(pid, []), config["min_signal_confidence"])
            projects.append(
                {
                    "project_id": pid,
                    "repository_id": str(row["repository_id"]),
                    "repository_slug": _slug(row["repository_name"]),
                    "project_path": row["project_path"],
                    "classification_status": row["classification_status"],
                    "classification_step_execution_id": row["classification_step_execution_id"],
                    "signal_set": set(names),
                    "facets": sig.facets(row),
                }
            )

        if not projects:
            return {
                "noop": True,
                "message": (
                    f"No eligible projects in '{engagement_id}' — "
                    f"nothing is NO_PATTERN_MATCHED or AMBIGUOUS across "
                    f"{coverage['repositories_included']} scanned repository(ies). A fully classified estate is a "
                    f"valid outcome."
                ),
                "coverage": coverage,
            }

        clusters = cluster_engine.build_clusters(projects, config)
        cluster_engine.pattern_proximity(clusters, db.active_pattern_signal_sets(conn), config)

        existing = db.load_existing_clusters(conn, engagement_id)
        for c in clusters:
            needs, reason = coverage_engine.rereview_decision(
                existing.get(c["cluster_id"]),
                c["member_count"],
                coverage["coverage_ratio"],
                config["min_rereview_members"],
            )
            c["needs_rereview"], c["rereview_reason"] = needs, reason

        db.upsert_clusters(conn, engagement_id, clusters, step_execution_id)
        stale_count = db.stale_cluster_count(conn, engagement_id)
        breakdown = db.eligibility_breakdown(conn, engagement_id)

    clustered = [c for c in clusters if not c["is_singleton"]]
    singletons = [c for c in clusters if c["is_singleton"]]
    summary = {
        "coverage": coverage,
        "projects_total": sum(breakdown.values()),
        "projects_eligible": len(projects),
        "projects_clustered": sum(c["member_count"] for c in clustered),
        "projects_singleton": len(singletons),
        "cluster_count": len(clustered),
        "singleton_count": len(singletons),
        # Over real clusters only, to stay consistent with cluster_count —
        # "0 clusters, largest 1" reads as a contradiction.
        "largest_cluster_size": max((c["member_count"] for c in clustered), default=0),
        "stale_cluster_count": stale_count,
        "needs_rereview_count": sum(1 for c in clusters if c["needs_rereview"]),
        "eligibility_breakdown": {
            k: v for k, v in sorted(breakdown.items()) if k in cluster_engine.ELIGIBLE_STATUSES
        },
        "excluded_insufficient_fingerprint": breakdown.get("INSUFFICIENT_FINGERPRINT", 0),
    }

    artifact = build_clusters_artifact(engagement_id, clusters, summary, config)
    body = serialise(artifact)
    output_dir.mkdir(parents=True, exist_ok=True)
    clusters_path = output_dir / "pattern-candidate-clusters.json"
    # write_bytes, not write_text: text mode on Windows translates \n to
    # \r\n, which would make the on-disk bytes disagree with the checksum.
    clusters_path.write_bytes(body)

    outcome = {
        "noop": False,
        "clusters_path": clusters_path,
        "checksum": "sha256:" + hashlib.sha256(body).hexdigest(),
        "cluster_count": len(clusters),
        "config_version": config_version,
        "coverage": coverage,
        "warnings": [],
    }

    # Narration runs AFTER the deterministic artifact is serialised and
    # checksummed, writes a different file, and cannot reach back. With
    # enable_narration false the step never enters this branch at all,
    # which is what "fully deterministic" means in Part E.
    enabled = config.get("enable_narration", True)
    if enabled:
        entries, warnings = narration_engine.narrate(clusters, config)
        outcome["warnings"] = warnings
    else:
        entries, warnings = [narration_engine.unnamed(c["cluster_id"]) for c in clusters], []

    status, reason = narration_engine.status_for(entries, warnings, enabled)
    outcome["narration_status"] = status
    outcome["narration_reason"] = reason

    with db.connect(database_url) as conn:
        db.apply_narration(conn, entries)
        db.record_run(
            conn, engagement_id, step_execution_id, summary, status, reason,
            sum(1 for e in entries if e["naming_source"] == "claude-code"), str(output_dir),
            cluster_count=len(clusters),
        )

    narration_artifact = narration_engine.build_artifact(engagement_id, entries, enabled, status, reason)
    narration_path = output_dir / "pattern-candidate-narration.json"
    narration_body = serialise(narration_artifact)
    narration_path.write_bytes(narration_body)
    outcome["narration_path"] = narration_path
    # Recorded, not asserted. Part A2 keeps narration off the verification
    # path: the two artifacts must not SHARE a checksum, so a reworded
    # suggestion never invalidates the deterministic one. It does not
    # follow that narration should have no hash at all — the step contract
    # requires one on every output, and knowing which narration you are
    # looking at is ordinary provenance. What must never happen is a
    # verifier treating a change here as tampering, which is why these are
    # two artifacts rather than one.
    outcome["narration_checksum"] = "sha256:" + hashlib.sha256(narration_body).hexdigest()
    outcome["named_count"] = sum(1 for e in entries if e["naming_source"] == "claude-code")
    return outcome


def retry_narration(database_url: str, engagement_id: str) -> dict:
    """Re-run narration against the clusters already in the database,
    without re-clustering.

    Safe precisely because the deterministic artifact does not depend on
    narration: there is nothing to recompute. Re-clustering instead would
    be actively wrong — the estate may have been rescanned since, so it
    could produce a DIFFERENT clustering and silently renumber shapes a
    human is mid-review on. This reads the stored clusters and only
    replaces their names.
    """
    _config_version, config = latest_config()
    with db.connect(database_url) as conn:
        run = db.latest_run(conn, engagement_id)
        clusters = db.clusters_for_narration(conn, engagement_id)

    if not clusters:
        return {
            "narration_status": "failed",
            "narration_reason": f"no clusters recorded for '{engagement_id}' — run step 5 first",
            "narrated_count": 0,
            "cluster_count": 0,
        }

    # Retry is an explicit human action, so it overrides enable_narration:
    # asking for narration and being told it is disabled in a config file
    # you cannot see from the UI is not a useful answer.
    entries, warnings = narration_engine.narrate(clusters, config)
    status, reason = narration_engine.status_for(entries, warnings, enabled=True)
    narrated = sum(1 for e in entries if e["naming_source"] == "claude-code")

    with db.connect(database_url) as conn:
        db.apply_narration(conn, entries)
        db.record_run(
            conn, engagement_id, None,
            {"cluster_count": len(clusters),
             "coverage": {"coverage_ratio": float(run["coverage_ratio"]) if run and run["coverage_ratio"] is not None else None,
                          "partial_estate": bool(run["partial_estate"]) if run else False}},
            status, reason, narrated, run["output_dir"] if run else None,
            cluster_count=len(clusters),
        )

    # Rewrite the narration artifact in place, so the file on disk and the
    # database do not disagree about what the clusters are called. The
    # clusters artifact beside it is untouched, and its checksum still
    # holds — which is the property that makes this action safe at all.
    if run and run["output_dir"]:
        out = Path(run["output_dir"])
        if out.is_dir():
            artifact = narration_engine.build_artifact(engagement_id, entries, True, status, reason)
            (out / "pattern-candidate-narration.json").write_bytes(serialise(artifact))

    return {
        "narration_status": status,
        "narration_reason": reason,
        "narrated_count": narrated,
        "cluster_count": len(clusters),
    }


def _run_process_adapter() -> None:
    context = json.loads(sys.stdin.read())
    engagement_id = context["parameters"]["engagement_id"]
    output_dir = Path(context["output_dir"])

    try:
        outcome = run_for_engagement(
            context["database_url"], engagement_id, output_dir, context.get("step_execution_id")
        )
    except Exception as exc:  # noqa: BLE001 - the contract requires FAILED, never a crash with no result
        print(json.dumps({"envelope_version": "1.0", "exit_status": "FAILED", "exit_message": f"{type(exc).__name__}: {exc}"}))
        return

    if outcome["noop"]:
        print(json.dumps({"envelope_version": "1.0", "exit_status": "NOOP", "exit_message": outcome["message"]}))
        return

    coverage = outcome["coverage"]
    message = (
        f"Clustered {outcome['cluster_count']} candidate shape(s) across "
        f"{coverage['repositories_included']} of {coverage['repositories_in_engagement']} repository(ies) "
        f"(coverage {coverage['coverage_ratio']:.2f})."
    )
    if coverage["partial_estate"]:
        message += f" Partial estate: {coverage['repositories_pending']} repository(ies) pending."
    # Say it in the message too. A diagnostic is easy to miss at fleet
    # scale, and "clustered 12 shapes" reads as unqualified success when
    # none of them got named.
    if outcome["narration_status"] != "succeeded":
        message += f" Narration {outcome['narration_status']}: {outcome['narration_reason']}"

    result = {
        "envelope_version": "1.0",
        "exit_status": "COMPLETED",
        "exit_message": message,
        # Part E: failure to narrate warns rather than fails the step, and
        # `diagnostics` is the contract's field for exactly that — "a
        # per-item problem that should not halt the whole step, surfaced in
        # the UI without failing it".
        "diagnostics": [
            {"level": "warning", "code": w["code"], "message": w["message"], "ref": None}
            for w in outcome["warnings"]
        ],
        "metrics": {
            "read_count": outcome["cluster_count"],
            "write_count": outcome["cluster_count"],
            "skip_count": 0,
            "commit_count": 1,
        },
        "outputs": [
            {
                "artifact_type": ARTIFACT_TYPE,
                "artifact_version": ARTIFACT_VERSION,
                "uri": f"file:///{outcome['clusters_path'].as_posix()}",
                "checksum": outcome["checksum"],
                # narration_status rides in StepOutput.metadata, NOT in the
                # artifact body. Part F puts volatile fields here precisely
                # so they stay out of the hashed content: a run with
                # narration disabled and one where it succeeded must produce
                # byte-identical clusters artifacts, and putting the status
                # in the summary would break that on the first failure.
                # Metadata is the designated place for a fact that is true
                # of the run rather than of the clustering.
                "metadata": {
                    "config_version": outcome["config_version"],
                    "cluster_count": outcome["cluster_count"],
                    "coverage_ratio": coverage["coverage_ratio"],
                    "partial_estate": coverage["partial_estate"],
                    "narration_status": outcome["narration_status"],
                    "narration_reason": outcome["narration_reason"],
                },
            },
            {
                "artifact_type": narration_engine.ARTIFACT_TYPE,
                "artifact_version": narration_engine.ARTIFACT_VERSION,
                "uri": f"file:///{outcome['narration_path'].as_posix()}",
                "checksum": outcome["narration_checksum"],
                "metadata": {
                    "named_cluster_count": outcome["named_count"],
                    # The flag a verifier reads: this artifact's checksum
                    # records what was produced, it does not assert what
                    # must be reproduced (Part A2).
                    "deterministic": False,
                },
            },
        ],
    }
    print(json.dumps(result))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", action="store_true", help="Run in regression-corpus mode; see corpus.py.")
    parser.add_argument("--write-expected", action="store_true", help="Seed/refresh corpus expectations.")
    parser.add_argument(
        "--retry-narration",
        metavar="ENGAGEMENT_ID",
        help="Re-run narration against the clusters already stored for this engagement, without re-clustering.",
    )
    parser.add_argument("--database-url", help="Required with --retry-narration.")
    args = parser.parse_args()

    if args.retry_narration:
        if not args.database_url:
            parser.error("--retry-narration requires --database-url")
        print(json.dumps(retry_narration(args.database_url, args.retry_narration), indent=2))
        return

    if args.corpus or args.write_expected:
        import corpus as corpus_mode

        if args.write_expected:
            corpus_mode.write_expected(CORPUS_DIR)
            return
        sys.exit(corpus_mode.run(CORPUS_DIR))

    _run_process_adapter()


if __name__ == "__main__":
    main()
