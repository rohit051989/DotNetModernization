# 26 — Running the Phase 0 Demo (Steps 1-5)

This doc is the practical run-through for actually exercising lifecycle steps 1-5
end to end — repository ingest, solution discovery, application fingerprinting,
pattern classification, and pattern discovery clustering — against a real
repository. It assumes `01-ENVIRONMENT-SETUP.md` has already been followed once
(Postgres up, backend venv created, `.env` in place, Alembic migrated, .NET SDK
installed).

Everything here is driven from **VS Code Tasks** — no manual multi-terminal
choreography required beyond the one background terminal for the backend.

## 0. One-time setup (per machine)

Run these once after cloning, in order, from the repository root.

```powershell
# 1. Bring up Postgres
cd docker
docker compose up -d
docker compose ps      # wait for "healthy"
cd ..

# 2. Backend venv + dependencies
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt

# 3. Environment file
copy .env.example .env

# 4. Apply migrations
alembic upgrade head

# 5. Seed the pattern catalog, lifecycle steps, and the demo engagement
#    (client-a-ocp4) that every script below assumes exists
python -m app.seed
cd ..
```

```powershell
# 6. Build step 3 (the one .NET step) -- see 01-ENVIRONMENT-SETUP.md section 8
#    for SDK version requirements first
cd steps\step-003-fingerprinting
dotnet publish src\Fingerprinting.Cli\Fingerprinting.Cli.csproj -c Release -o publish
cd ..\..
```

Then start the backend in its **own terminal tab and leave it alone** — never type
into this tab again once it's up, or `--reload`'s file watcher can kill an
in-flight request:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8001
```

Wait for `Application startup complete.` before doing anything else. Confirm it's
alive from a **second** terminal tab: `http://127.0.0.1:8001/api/health` should
return `{"status":"ok","database":"connected"}`.

With the backend running, register this platform's steps and activate the job
definition (also one-time, safe to re-run — both scripts upsert):

```powershell
cd backend
& .\.venv\Scripts\python.exe e2e_run\register_steps.py
& .\.venv\Scripts\python.exe e2e_run\store_job_v6.py
cd ..
```

## 1. Running the demo day to day

Open the repository folder in VS Code, then **Terminal → Run Task…** (or
`Ctrl+Shift+B` for the default) and pick one:

| Task | What it does |
|---|---|
| **Run E2E Demo (steps 1-5)** | Registers/rescans the synthetic sample repo (`_sample-repos/legacy-grpc-suite`), runs steps 1-4 against it for real, then runs step 5 (pattern discovery) across the whole engagement. Default build task. |
| **Run Step 5 Only (pattern discovery)** | Runs just step 5 standalone against whatever is already fingerprinted in the engagement — no job engine, pure `main.py` invocation. Fastest way to demo the clustering math on its own; does not need the backend running. |
| **Run Real Repo Demo (NetCoreUpgrade)** | Registers a real, external repository and runs steps 1-4 against it, then re-runs step 5 engagement-wide so it's considered alongside everything else. Edit `backend/e2e_run/register_netcoreupgrade.py`'s `LOCAL_PATH` / `CLONE_URL` / `REPO_NAME` to point at a different real repository if you want to test your own. |

All three write into `_run-output/` at the repository root — see
`_run-output/README.md` for exactly what lands where and why.

## 2. Known gotchas (already worked around in the scripts, documented here so
##    they aren't rediscovered from scratch)

- **uvicorn's `--reload` watcher can kill an in-flight request** if a file under
  `backend/` changes while a script is mid-request (e.g. right after adding a new
  `e2e_run/*.py` file). The registration scripts retry once automatically on
  `ConnectionResetError`; if a script still fails this way, just re-run the task.
- **A new terminal *tab* in an already-running VS Code window does not pick up an
  updated Windows `PATH`.** If `dotnet` or `python` suddenly "isn't recognized"
  right after installing something, close and reopen VS Code entirely rather than
  opening a new tab.
- **Step 3's subprocess doesn't inherit your interactive shell's PATH.** This is
  why `register_steps.py` sets `DOTNET_ROOT` explicitly in step 3's
  `adapter_config.env` — MSBuildLocator checks that variable before PATH. If you
  ever re-register steps by hand and step 3 fails with "Path to dotnet executable
  is not set," this is why.
- **PowerShell's `Set-Content -Encoding utf8` writes a BOM.** Anything reading a
  file produced that way (e.g. `step5-envelope.json`) uses Python's
  `utf-8-sig` encoding to strip it, not plain `utf-8`.
