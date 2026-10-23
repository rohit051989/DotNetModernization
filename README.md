# Modernization Platform

The Modernization Platform runs and tracks the modernization of a .NET estate. It discovers what each repository
contains, finds the patterns that need to change (WCF, Windows-only code, outdated packages and the rest), proposes
how to resolve each one, and prepares and verifies each conversion. It runs on one machine, for one operator, with
its own PostgreSQL schema.

This folder is the platform. It arrives as releases: each one is committed to this folder on the platform's branch
of your repository. **Do not edit the files in this folder**: the next release replaces them, and your changes would
be lost or would block it. What belongs to your machine (`backend\.env`, `frontend\.env`, the Python environment,
`node_modules`, the published step programs, and the data in `RUNS_DIR`) is never part of a release and is never
touched by one.

The full guide is [`docs/VDI-SETUP.md`](docs/VDI-SETUP.md). This page is the short version. The commands assume this
folder is `C:\MP\client\modernization-platform`; use your own path.

## 1. Prerequisites

- **Python** 3.11 to 3.14, a final release (tested: 3.14.8)
- **Node.js** 20.19 or later 20.x, or 22.12 or later (npm comes with it)
- **.NET SDK** 10.0.100 or later
- **git** 2.17 or later, with long paths on: `git config --global core.longpaths true`
- **A PostgreSQL 17 database** and a login for the platform, with the right to create tables in its schema
- **Package sources** your machine can reach, for pip, npm and NuGet: the public registries, or your own mirrors

None of these needs administrator rights when installed for your user. The guide's "Before starting", "Account
settings" and "Package sources" sections give the detail.

## 2. Create the settings files

```powershell
cd C:\MP\client\modernization-platform; Copy-Item backend\.env.example backend\.env; Copy-Item frontend\.env.example frontend\.env
```

Edit `backend\.env`. At least: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_SCHEMA`, `DB_USER`, `DB_PASSWORD`, and
`RUNS_DIR`, an absolute folder **outside** this repository where the platform keeps its run output. The package
source keys stay empty when the public registries are reachable. Every key is explained in the guide's
"backend\.env". Both files stay on your machine: they are never committed.

## 3. Preflight, then bootstrap

Preflight checks every tool, package source, the database and `RUNS_DIR`, and says exactly what is missing:

```powershell
cd C:\MP\client\modernization-platform; python scripts\preflight.py
```

Fix every `MISSING` line (the guide's "Preflight" says how), then bootstrap. It creates the Python environment,
installs the dependencies, builds the step programs, creates the schema and loads the catalog. A second run skips what
is already done.

```powershell
cd C:\MP\client\modernization-platform; powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

It ends with `Bootstrap complete`.

## 4. Start the backend and the frontend

Two PowerShell windows, each left open: they show the logs.

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

```powershell
cd C:\MP\client\modernization-platform\frontend; npm run dev -- --port 5174 --strictPort
```

Open `http://localhost:5174/`. The header shows a green **connected** badge when the frontend reaches the backend.

## 5. Create an engagement

An engagement is one client program. In the UI: **+ New engagement**, beside the **View** selector. Or from the
command line:

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.engagements.cli create --name "Client A" --target-framework net10.0
```

Then register the repositories to modernize (the guide's "Registering a client repository").

## 6. Updating to a new release

A new release arrives as a commit to this folder on the platform's branch. To install it:

1. Stop the backend and the frontend (**Ctrl+C** in each window), once no discovery or verification is running (the
   repository's **Executions** tab).
2. Pull the branch:

   ```powershell
   git -C C:\MP\client pull --ff-only
   ```

3. Run bootstrap again. It updates only what the release changed, and keeps all your data.

   ```powershell
   cd C:\MP\client\modernization-platform; powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
   ```

4. Start the backend and the frontend again.

Never update by editing the platform's files: changes arrive with each release. `PLATFORM_SOURCE.json` records which
release this folder holds. What each release changes is in the guide's "Appendix: upgrading from a release bundle".

## More

- [`docs/VDI-SETUP.md`](docs/VDI-SETUP.md): the full installation and operating guide
- [`docs/01-ENVIRONMENT-SETUP.md`](docs/01-ENVIRONMENT-SETUP.md): the platform's environment, network destinations
  and what lives in its database schema
