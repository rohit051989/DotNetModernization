"""Registers steps 1, 2, 3 (stub), 4, 5 as real wf_step_registrations rows.

Run this any time after `python -m app.seed` has reset every step back to
stub placeholders -- seeding always does that (seed_lifecycle_steps()), so
this script is what turns the ones with real code back into real, runnable
registrations. Idempotent: register_step() always upserts by step_name.

Process-adapter steps (2, 4, 5) point straight at the backend venv's own
python.exe by an explicit path rather than relying on PATH-search of a bare
"python" -- on this machine the interactive shell's "python" and the
running uvicorn process's PATH don't necessarily agree on which install
that resolves to (that's what caused solution-discovery's
"ModuleNotFoundError: No module named 'psycopg'" -- it ran under a python
that isn't this venv), so pinning the path sidesteps that entirely.

Usage (from backend/, venv activated, uvicorn already running on 8001):
    python e2e_run/register_steps.py
"""
import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8001/api/workflow/steps"
VENV_PYTHON = "backend/.venv/Scripts/python.exe"  # resolved against PLATFORM_ROOT by the process adapter

STEPS = [
    {
        "step_name": "repository-ingest",
        "lifecycle_step_no": 1,
        "display_name": "Repository Ingest",
        "owner_code": "P",
        "version": "1.0.0",
        "owner_team": "Platform",
        "viewpoint": "FUNCTIONAL",
        "implementation_status": "implemented",
        "consumes": [],
        "produces": [{"artifact_type": "repository-inventory", "artifact_version": "1.1.0"}],
        "adapter_type": "python",
        "adapter_config": {"entrypoint": "app.steps.repository_ingest:run"},
    },
    {
        "step_name": "solution-discovery",
        "lifecycle_step_no": 2,
        "display_name": "Solution Discovery",
        "owner_code": "P",
        "version": "1.0.0",
        "owner_team": "Platform",
        "viewpoint": "FUNCTIONAL",
        "implementation_status": "implemented",
        "consumes": [
            {"artifact_type": "repository-inventory", "version_range": "^1.0.0", "optional": False}
        ],
        "produces": [{"artifact_type": "solution-project-inventory", "artifact_version": "2.0.0"}],
        "adapter_type": "process",
        "adapter_config": {"command": [VENV_PYTHON, "steps/step-002-solution-discovery/main.py"]},
    },
    {
        # Built for real now: dotnet publish src/Fingerprinting.Cli -c Release
        # -o publish (steps/step-003-fingerprinting/README.md). The engine
        # runs the published exe directly, never `dotnet run`.
        "step_name": "application-fingerprinting",
        "lifecycle_step_no": 3,
        "display_name": "Application Fingerprinting",
        "owner_code": "P",
        "version": "1.0.0",
        "owner_team": "Platform",
        "viewpoint": "FUNCTIONAL",
        "implementation_status": "implemented",
        "consumes": [
            {"artifact_type": "solution-project-inventory", "version_range": "^2.0.0", "optional": False}
        ],
        "produces": [{"artifact_type": "application-fingerprint", "artifact_version": "1.0.0"}],
        "adapter_type": "process",
        "adapter_config": {
            "command": ["steps/step-003-fingerprinting/publish/Fingerprinting.Cli.exe"],
            # MSBuildLocator (inside the exe) probes DOTNET_ROOT/DOTNET_HOST_PATH/
            # PATH to find the dotnet install -- set explicitly rather than
            # relying on the backend process's own (possibly stale) PATH.
            "env": {"DOTNET_ROOT": "C:\\Program Files\\dotnet"},
        },
    },
    {
        "step_name": "pattern-classification",
        "lifecycle_step_no": 4,
        "display_name": "Pattern Classification",
        "owner_code": "P",
        "version": "1.0.0",
        "owner_team": "Platform",
        "viewpoint": "FUNCTIONAL",
        "implementation_status": "implemented",
        "consumes": [
            {"artifact_type": "application-fingerprint", "version_range": "^1.0.0", "optional": False}
        ],
        "produces": [{"artifact_type": "application-classification", "artifact_version": "1.0.0"}],
        "adapter_type": "process",
        "adapter_config": {"command": [VENV_PYTHON, "steps/step-004-classification/main.py"]},
    },
    {
        "step_name": "pattern-discovery-clustering",
        "lifecycle_step_no": 5,
        "display_name": "Pattern Discovery Clustering",
        "owner_code": "P",
        "version": "1.0.0",
        "owner_team": "Platform",
        "viewpoint": "FUNCTIONAL",
        "implementation_status": "implemented",
        "consumes": [],
        "produces": [],
        "adapter_type": "process",
        "adapter_config": {"command": [VENV_PYTHON, "steps/step-005-pattern-discovery/main.py"]},
    },
]

for decl in STEPS:
    body = json.dumps(decl).encode("utf-8")
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(
                BASE, data=body, method="POST", headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req) as resp:
                print(f"OK   {decl['step_name']:30s} -> {resp.status}")
            break
        except urllib.error.HTTPError as e:
            print(f"FAIL {decl['step_name']:30s} -> {e.code} {e.read().decode('utf-8', errors='replace')}")
            break
        except (urllib.error.URLError, ConnectionResetError, ConnectionError) as e:
            if attempt == 1:
                print(f"WARN {decl['step_name']:30s} -> {e!r}, retrying once...")
                time.sleep(1.5)
                continue
            print(f"FAIL {decl['step_name']:30s} -> {e!r} (gave up after retry)")
