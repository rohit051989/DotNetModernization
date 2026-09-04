"""Registers the synthetic sample repo (or, if it's already registered from
a prior attempt, rescans it instead) and polls phase0-repository-discovery
to completion, printing every step's outcome.

Usage (from backend/, venv activated, uvicorn running on 8001,
register_steps.py + store_job_v6.py already run successfully):
    python e2e_run/register_repo_and_run.py
"""
import json
import time
import urllib.request

ENGAGEMENT_ID = "client-a-ocp4"
LOCAL_PATH = r"D:\dotnet-modernization\_sample-repos\legacy-grpc-suite"
REPO_NAME = "Legacy gRPC Suite"
BASE = "http://127.0.0.1:8001"


def post(path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def get(path):
    req = urllib.request.Request(BASE + path, method="GET")
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


status, body = post(
    f"/api/engagements/{ENGAGEMENT_ID}/repositories/register",
    {
        "source_type": "local_path",
        "local_path": LOCAL_PATH,
        "name": REPO_NAME,
        "clone_url": "https://github.com/example/legacy-grpc-suite.git",
        "description": "Synthetic sample: two near-identical gRPC services, built to land on NO_PATTERN_MATCHED.",
        "criticality": "medium",
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
    match = next((r for r in repos if r.get("local_path") == LOCAL_PATH or r.get("name") == REPO_NAME), None)
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
