"""Lifecycle step 5 — pattern discovery clustering for unmatched
applications.

Reads a StepContext JSON envelope from stdin, writes a StepResult JSON
envelope to stdout — see 11-STEP-CONTRACT.md and
23-STEP-005-PATTERN-DISCOVERY.md.

Engagement-scoped, not repository-scoped (Part B) — this is the one
structural difference from steps 1-4's `run(context)` shape: there is no
`parameters.repository_id`, and the step's real input is not `inputs` at
all but a direct read across every in-scope repository in the engagement's
`fingerprint_signals` / `project_fingerprints` tables (Part A3). This
package still must not import `backend.app` — raw psycopg only, same rule
as steps 2 and 3 — but unlike them it cannot run with `database_url`
omitted, because the database *is* its primary input path, not an optional
persistence side-effect. See the README for what "standalone" means for
this step given that constraint.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path

from clustering import artifact as artifact_builder
from clustering import assembly, persistence
from clustering.llm_client import LlmClient
from clustering.llm_pass import run_llm_pass
from clustering.similarity import DEFAULT_CATEGORY_WEIGHTS
from clustering.structural_pass import DEFAULT_THRESHOLD_STRONG, DEFAULT_THRESHOLD_WEAK, run_structural_pass


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _failed(message: str) -> dict:
    return {"envelope_version": "1.0", "exit_status": "FAILED", "exit_message": message}


def _sha256_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def run(context: dict) -> dict:
    parameters = context.get("parameters") or {}
    engagement_id = parameters.get("engagement_id")
    if not engagement_id:
        return _failed("parameters.engagement_id is required for pattern-discovery-clustering")

    database_url = context.get("database_url")
    if not database_url:
        # Unlike steps 2 and 3, database_url is not optional here — it is
        # this step's only input path (Part A3), not a persistence
        # side-effect a standalone run can skip.
        return _failed("database_url is required for pattern-discovery-clustering (it is this step's input path, not only its output)")

    config = context.get("config") or {}
    threshold_strong = float(config.get("threshold_strong", DEFAULT_THRESHOLD_STRONG))
    threshold_weak = float(config.get("threshold_weak", DEFAULT_THRESHOLD_WEAK))
    category_weights = {**DEFAULT_CATEGORY_WEIGHTS, **(config.get("category_weights") or {})}
    llm_model = config.get("llm_model")

    now = _now_iso()
    diagnostics: list[dict] = []

    repository_of = persistence.load_candidate_applications(database_url, engagement_id)
    unmatched_input_count = len(repository_of)

    if unmatched_input_count == 0:
        rows: list[dict] = []
        persistence.replace_all(
            database_url,
            engagement_id,
            rows=rows,
            repository_of=repository_of,
            source_job_execution_id=context.get("job_execution_id"),
        )
        exit_message = f"No unmatched applications found for engagement '{engagement_id}'; nothing to cluster."
        metrics = {"read_count": 0, "write_count": 0, "skip_count": 0, "commit_count": 1}
        artifact = artifact_builder.build_artifact(
            engagement_id,
            rows,
            unmatched_input_count=0,
            threshold_strong=threshold_strong,
            threshold_weak=threshold_weak,
            category_weights=category_weights,
        )
        return _finish(context, artifact, exit_message, metrics, diagnostics, now)

    project_ids = list(repository_of)
    app_signals = persistence.load_application_signals(database_url, project_ids)

    clusters, residue_ids, pairwise = run_structural_pass(
        app_signals, threshold_strong=threshold_strong, weights=category_weights
    )

    if residue_ids:
        signal_details = persistence.load_signal_details(database_url, residue_ids)
        client = LlmClient(model=llm_model) if llm_model else LlmClient()
        llm_clusters, residue_ids, llm_diagnostics = run_llm_pass(
            residue_ids,
            app_signals,
            signal_details,
            pairwise,
            threshold_weak=threshold_weak,
            client=client,
        )
        clusters = sorted([*clusters, *llm_clusters], key=lambda c: c.members)
        diagnostics.extend(llm_diagnostics)

    rows = assembly.assemble_rows(
        engagement_id,
        clusters,
        residue_ids,
        pairwise,
        threshold_weak=threshold_weak,
        threshold_strong=threshold_strong,
    )

    persistence.replace_all(
        database_url,
        engagement_id,
        rows=rows,
        repository_of=repository_of,
        source_job_execution_id=context.get("job_execution_id"),
    )

    candidate_pattern_count = sum(1 for r in rows if r["status"] == "candidate_pattern")
    unclustered_count = len(rows) - candidate_pattern_count
    exit_message = (
        f"{unmatched_input_count} candidate application(s) across engagement '{engagement_id}': "
        f"{candidate_pattern_count} candidate pattern(s), {unclustered_count} unclustered."
    )
    metrics = {
        "read_count": unmatched_input_count,
        "write_count": len(rows),
        "skip_count": sum(1 for d in diagnostics if d.get("level") == "warning"),
        "commit_count": 1,
    }
    artifact = artifact_builder.build_artifact(
        engagement_id,
        rows,
        unmatched_input_count=unmatched_input_count,
        threshold_strong=threshold_strong,
        threshold_weak=threshold_weak,
        category_weights=category_weights,
    )
    return _finish(context, artifact, exit_message, metrics, diagnostics, now)


def _finish(context: dict, artifact: dict, exit_message: str, metrics: dict, diagnostics: list[dict], now: str) -> dict:
    output_dir = Path(context["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "pattern-discovery-clusters.json"
    # generated_at deliberately excluded from the file so unchanged input
    # yields an identical checksum — same rationale as steps 1 and 2.
    output_path.write_text(
        json.dumps(artifact, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return {
        "envelope_version": "1.0",
        "exit_status": "COMPLETED",
        "exit_message": exit_message,
        "metrics": metrics,
        "diagnostics": diagnostics,
        "outputs": [
            {
                "artifact_type": artifact_builder.ARTIFACT_TYPE,
                "artifact_version": artifact_builder.ARTIFACT_VERSION,
                "uri": output_path.as_uri(),
                "checksum": _sha256_file(output_path),
                "metadata": {"generated_at": now},
            }
        ],
    }


if __name__ == "__main__":
    # lstrip a BOM: PowerShell's `Get-Content | python main.py` can inject
    # one depending on console encoding, even when the source file itself
    # has none — same as step 2.
    _raw_context = json.loads(sys.stdin.read().lstrip("﻿"))
    try:
        _result = run(_raw_context)
    except Exception as exc:  # a "process"-style invocation must still emit valid JSON
        _result = {"envelope_version": "1.0", "exit_status": "FAILED", "exit_message": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(_result))
