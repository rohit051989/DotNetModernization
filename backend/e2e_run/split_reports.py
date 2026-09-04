"""Splits the legacy-grpc-suite run into a per-repo step-4 file, and copies
step 5's engagement-wide envelope alongside its artifact, so each piece can
be shared on its own -- see _run-output/README.md for the full layout.

  _run-output/by-repository/legacy-grpc-suite/full-e2e-result.json          (unchanged -- everything together)
  _run-output/by-repository/legacy-grpc-suite/step4-classification-result.json
  _run-output/engagement-wide/pattern-discovery/pattern-discovery-clusters.json  (already written by step 5 itself)
  _run-output/engagement-wide/pattern-discovery/step5-envelope.json             (copied from the step's own run)

Usage (from backend/, venv activated, AFTER build_full_report.py has run
AND step 5's envelope has been captured to step5-envelope.json -- see the
Get-Content | python main.py | Set-Content command that goes with this):
    python e2e_run/split_reports.py
"""
import json
import pathlib

RUN_OUTPUT = pathlib.Path(r"D:\dotnet-modernization\_run-output")
REPO_DIR = RUN_OUTPUT / "by-repository" / "legacy-grpc-suite"
FULL_REPORT = REPO_DIR / "full-e2e-result.json"
STEP5_DIR = RUN_OUTPUT / "engagement-wide" / "pattern-discovery"
STEP5_ENVELOPE_SOURCE = pathlib.Path(r"D:\dotnet-modernization\steps\step-005-pattern-discovery\step5-envelope.json")
STEP5_ARTIFACT = STEP5_DIR / "pattern-discovery-clusters.json"

full = json.loads(FULL_REPORT.read_text(encoding="utf-8"))

execution = full["phase0_repository_discovery_execution"]
step4 = next((s for s in execution["steps"] if s["step_name"] == "pattern-classification"), None)
if step4 is None:
    raise SystemExit("No 'pattern-classification' step found in the execution -- did the job run far enough?")

step4_report = {
    "engagement_id": full["engagement_id"],
    "repository": full["repository"],
    "job_execution_id": execution["id"],
    "job_definition_version": execution["job_definition_version"],
    "step": step4,
    "classification_results": full.get("pattern_classification_results"),
}
(REPO_DIR / "step4-classification-result.json").write_text(
    json.dumps(step4_report, indent=2, default=str), encoding="utf-8"
)
print(f"Wrote {REPO_DIR / 'step4-classification-result.json'}")

STEP5_DIR.mkdir(parents=True, exist_ok=True)
if STEP5_ENVELOPE_SOURCE.exists():
    envelope = json.loads(STEP5_ENVELOPE_SOURCE.read_text(encoding="utf-8-sig"))
    (STEP5_DIR / "step5-envelope.json").write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    print(f"Wrote {STEP5_DIR / 'step5-envelope.json'}")
else:
    print(f"NOTE: {STEP5_ENVELOPE_SOURCE} not found -- run step 5 with output captured first (see instructions).")

if not STEP5_ARTIFACT.exists():
    print(f"NOTE: {STEP5_ARTIFACT} not found -- step 5 writes this itself when it runs.")
