"""Assembles one consolidated JSON covering the whole steps 1-5 run:
the phase0-repository-discovery job execution (steps 1-4, with every
resolved input and produced artifact), step 4's actual classification
results (which pattern each project matched, if any), plus step 5's
standalone clustering result read back off disk. Written as a single file
so the whole end-to-end run can be inspected or shared as one JSON
document.

Output layout (see _run-output/README.md):
  _run-output/by-repository/legacy-grpc-suite/full-e2e-result.json  <- this file
  _run-output/engagement-wide/pattern-discovery/...                <- step 5, shared across all repos

Usage (from backend/, venv activated, uvicorn running on 8001, AFTER
register_repo_and_run.py and the step 5 standalone run have both
completed):
    python e2e_run/build_full_report.py
"""
import json
import pathlib
import urllib.request

BASE = "http://127.0.0.1:8001"
ENGAGEMENT_ID = "client-a-ocp4"
REPO_SLUG = "legacy-grpc-suite"
STEP5_OUTPUT = pathlib.Path(r"D:\dotnet-modernization\_run-output\engagement-wide\pattern-discovery\pattern-discovery-clusters.json")
REPORT_OUT = pathlib.Path(r"D:\dotnet-modernization\_run-output\by-repository\legacy-grpc-suite\full-e2e-result.json")


def get(path):
    with urllib.request.urlopen(urllib.request.Request(BASE + path, method="GET")) as resp:
        return json.loads(resp.read().decode("utf-8"))


# Find the repository by its known slug (RepositorySummary, from the list
# endpoint, doesn't carry local_path -- only RepositoryDetail does).
repos = get(f"/api/engagements/{ENGAGEMENT_ID}/repositories")
repo = next((r for r in repos if r.get("slug") == REPO_SLUG), None)
if repo is None:
    raise SystemExit(f"No repository found with slug={REPO_SLUG!r} -- run register_repo_and_run.py first.")

# Latest execution for this repository (list_executions returns newest first).
executions = get(f"/api/workflow/executions?repository_id={repo['id']}&limit=1")
if not executions:
    raise SystemExit(f"No executions found for repository_id={repo['id']!r}.")
latest_execution_id = executions[0]["id"]

execution_detail = get(f"/api/workflow/executions/{latest_execution_id}")

# Step 4's actual classification results for this repository -- which
# pattern (if any) each project matched, its score, and why.
classifications = get(f"/api/repositories/{repo['id']}/classifications")

if not STEP5_OUTPUT.exists():
    raise SystemExit(
        f"{STEP5_OUTPUT} doesn't exist yet -- run step 5 standalone first: "
        "cd ..\\steps\\step-005-pattern-discovery ; Get-Content sample-context.json | python main.py"
    )
step5_result = json.loads(STEP5_OUTPUT.read_text(encoding="utf-8"))

report = {
    "engagement_id": ENGAGEMENT_ID,
    "repository": {
        "id": repo["id"],
        "slug": repo["slug"],
        "name": repo["name"],
    },
    "phase0_repository_discovery_execution": execution_detail,
    "pattern_classification_results": classifications,
    "pattern_discovery_clustering_result": step5_result,
}

REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
REPORT_OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
print(f"Wrote consolidated report -> {REPORT_OUT}")
print(f"  job execution steps: {len(execution_detail.get('steps', []))}")
print(f"  classifications: {len(classifications.get('projects', []))}")
print(f"  step 5 clusters: {len(step5_result.get('clusters', []))}")
