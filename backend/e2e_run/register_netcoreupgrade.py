"""Registers a REAL external repository (not a synthetic sample) into the
same engagement used by the rest of this demo, to prove the pipeline runs
against genuine code it was never built around.

Repo: https://github.com/sandeeptulixolo/.NetCoreUpgrade (VulnerableConsoleApp)
  - a single console app (one .csproj), no .sln recognised (it ships a
    newer .slnx file, which step 2's solution scan does not parse -- but
    step 2 discovers projects independently of solutions, so the .csproj
    is still found and parsed as a standalone project).
  - because it's the only application from this repo, step 5 cannot form a
    *new* cluster from it alone: expect it to land as unclustered residue
    unless it happens to structurally match something else already in the
    engagement. That's an expected, informative outcome, not a bug.

Usage (from backend/, venv activated, uvicorn running on 8001,
register_steps.py + store_job_v6.py already run successfully):
    python e2e_run/register_netcoreupgrade.py
"""
import json
import time
import urllib.error
import urllib.request

ENGAGEMENT_ID = "client-a-ocp4"
LOCAL_PATH = r"D:\NetCoreUpgrade\.NetCoreUpgrade"
REPO_NAME = "VulnerableConsoleApp (NetCoreUpgrade)"
CLONE_URL = "https://github.com/sandeeptulixolo/.NetCoreUpgrade"
BASE = "http://127.0.0.1:8001"


def _with_retry(fn, *args, **kwargs):
    """uvicorn's --reload watcher can restart mid-request if backend/ files
    changed recently (e.g. this script itself just got added) -- one retry
    covers that without masking a genuinely dead backend."""
    try:
        return fn(*args, **kwargs)
    except (urllib.error.URLError, ConnectionResetError, ConnectionError) as e:
        print(f"WARN request failed -> {e!r}, retrying once in 2s (likely uvicorn --reload restart)...")
        time.sleep(2)
        return fn(*args, **kwargs)


def post(path, body):
    def _do():
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(BASE + path, data=data, method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))
    return _with_retry(_do)


def get(path):
    def _do():
        req = urllib.request.Request(BASE + path, method="GET")
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    return _with_retry(_do)


status, body = post(
    f"/api/engagements/{ENGAGEMENT_ID}/repositories/register",
    {
        "source_type": "local_path",
        "local_path": LOCAL_PATH,
        "name": REPO_NAME,
        "clone_url": CLONE_URL,
        "description": "Real external repo (not synthetic): single console app with intentional "
                        "security-vulnerability demo classes. Used to test the pipeline against code "
                        "it was never designed around.",
        "criticality": "low",
        "retirement_status": "active",
    },
)
print(f"register_repository -> {status}")
print(json.dumps(body, indent=2))

job_execution_id = None

if status in (200, 201, 202):
    job_execution_id = body["job_execution_id"]
elif status == 409:
    print("\nAlready registered from an earlier attempt -- looking it up and rescanning instead.")
    status, repos = get(f"/api/engagements/{ENGAGEMENT_ID}/repositories?q={REPO_NAME.replace(' ', '%20')}")
    match = next((r for r in repos if r.get("name") == REPO_NAME), None)
    if match is None:
        raise SystemExit(f"409 on register but couldn't find a matching repo via list -- repos seen: {repos}")
    repo_id = match["id"]
    print(f"Found existing repository_id={repo_id}, rescanning...")
    status, body = post(f"/api/repositories/{repo_id}/rescan", {})
    print(f"rescan_repository -> {status}")
    print(json.dumps(body, indent=2))
    if status not in (200, 201, 202):
        raise SystemExit("Rescan failed too -- stopping here.")
    job_execution_id = body["job_execution_id"]
else:
    raise SystemExit("Registration failed for a reason other than duplicate -- stopping here (see body above).")

print(f"\nPolling job_execution_id={job_execution_id} ...")

TERMINAL = {"COMPLETED", "FAILED", "STOPPED", "ABANDONED"}
execution = {}
for _ in range(60):
    status, execution = get(f"/api/workflow/executions/{job_execution_id}")
    batch_status = execution.get("batch_status")
    print(f"  batch_status={batch_status}")
    if batch_status in TERMINAL:
        break
    time.sleep(2)
else:
    print("Timed out waiting for a terminal status -- showing whatever we last saw.")

print("\n=== Step-by-step outcome ===")
for step in execution.get("steps", []):
    print(
        f"  [{step['sequence']}] {step['step_name']:28s} "
        f"batch={step['batch_status']:10s} exit={str(step['exit_status']):16s} "
        f"skip_reason={step['skip_reason']}"
    )
    if step.get("exit_message"):
        print(f"       {step['exit_message']}")
    for out in step.get("outputs_produced", []):
        print(f"       produced: {out['artifact_type']}@{out['artifact_version']}")

print("\nFull execution detail:")
print(json.dumps(execution, indent=2, default=str))
