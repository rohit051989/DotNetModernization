"""Re-stores phase0-repository-discovery.yaml as version 6 and activates it.

Version 5 is already stored but stuck at is_active=False (validation failed
while every step was still a stub with no declared produces/consumes --
register_steps.py fixes that root cause). Storing a NEW version re-runs
validation against the now-real step registrations. Bumping the version
number avoids the 409 DuplicateJobVersionError re-posting version 5 would
hit.

Usage (from backend/, venv activated, uvicorn running on 8001,
register_steps.py already run):
    python e2e_run/store_job_v6.py
"""
import json
import pathlib
import urllib.request

JOB_YAML_PATH = pathlib.Path(__file__).resolve().parents[1] / "app" / "jobs" / "phase0-repository-discovery.yaml"
BASE = "http://127.0.0.1:8001/api/workflow/jobs"

text = JOB_YAML_PATH.read_text(encoding="utf-8")
if "version: 5" not in text:
    raise SystemExit(f"Expected 'version: 5' in {JOB_YAML_PATH}, didn't find it -- check the file by hand.")
text_v6 = text.replace("version: 5", "version: 6", 1)

body = json.dumps({"yaml": text_v6, "activate": True}).encode("utf-8")
req = urllib.request.Request(BASE, data=body, method="POST", headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        print(f"Stored OK -> {resp.status}")
        print(json.dumps(result, indent=2, default=str))
except urllib.error.HTTPError as e:
    print(f"FAIL -> {e.code}")
    print(e.read().decode("utf-8", errors="replace"))
