# Modernization Platform

The Modernization Platform runs and tracks the modernization of a .NET estate. It discovers what each repository
contains, finds the patterns that need to change (WCF, Windows-only code, outdated packages and the rest), proposes
how to resolve each one, and prepares and verifies each conversion. It runs on one machine, for one operator, with
its own PostgreSQL schema.

This folder is the platform. It arrives as updates from the platform's own master branch: each one is committed to
this folder on the platform's branch of your repository. The folder is either a folder inside a repository shared
with other work, where updates touch only that folder, or the root of a repository dedicated to the platform, laid
out exactly as the platform's own, where the whole repository is the platform: there, the platform's `README.md`,
`.gitignore` and other root files replace any of the same name, and files of yours that were never the platform's
are kept. The guide's "Two layouts" says when to use each. What belongs to your machine (`backend\.env`,
`frontend\.env`, the Python environment, `node_modules`, the published step programs, and the data in `RUNS_DIR`) is
never part of an update and is never touched by one.

**Changes to the platform may be made here**, committed on the platform's branch (or on a branch such as
`release/<feature>`) and pushed. The platform's team imports them into the platform's own repository, and they come
back to this folder, and to every other installation, with the next update. An update delivered before they are
imported overwrites them, and warns that it did: tell the platform's team when there is something to import. Never
commit secrets, `.env` files or large binaries: the import refuses them.

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

## 5. The first admin, and an engagement

Once, at installation, create the first admin: the person setting the platform up, on this machine (it asks for a
password, 12 characters or more). Then sign in at `http://localhost:5174/` with it:

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.users create-first-admin --login jdoe --name "Jane Doe"
```

The admin registers everyone else, in the **Users** tab: each person's Windows account and machines; they sign in on
their own machine, with their own platform, against the same database (the guide's "Users and sign-in").

An engagement is one client program, created by an admin. In the UI: **+ New engagement**, beside the **View**
selector. Or from the command line:

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.engagements.cli create --name "Client A" --target-framework net10.0
```

Then register the repositories to modernize (the guide's "Registering a client repository").

## 6. Updating

An update arrives as a commit to this folder on the platform's branch. To install it:

1. Stop the backend and the frontend (**Ctrl+C** in each window), once no discovery or verification is running (the
   repository's **Executions** tab).
2. Pull the branch:

   ```powershell
   git -C C:\MP\client pull --ff-only
   ```

3. Read the guide's "Upgrade notes" for every entry newer than the commit you had (`previousCommit` in
   `PLATFORM_SOURCE.json`). They say what needs doing besides bootstrap: a package your mirror must carry, a new
   setting, a rescan. Most updates need nothing more.
4. Run bootstrap again. It updates only what the update changed, and keeps all your data.

   ```powershell
   cd C:\MP\client\modernization-platform; powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
   ```

5. Start the backend and the frontend again, and do any rescan the notes asked for.

Updates arrive as commits; changes made here go back the other way, through the import (above). Never edit
`PLATFORM_SOURCE.json`: it records which commit of the platform this folder holds (`commit`), and the tag when one
happens to point at it, and the import starts from it.

## More

- [`docs/VDI-SETUP.md`](docs/VDI-SETUP.md): the full installation and operating guide
- [`docs/01-ENVIRONMENT-SETUP.md`](docs/01-ENVIRONMENT-SETUP.md): the platform's environment, network destinations
  and what lives in its database schema
