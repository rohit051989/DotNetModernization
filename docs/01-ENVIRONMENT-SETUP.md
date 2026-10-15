# 01 — Environment Setup (Windows)

All commands are **PowerShell**. Run from the repository root unless stated.
Chain commands with `;`, not `&&`.

## 0. Prerequisites to verify first

Claude Code: check each of these and report versions before proceeding. If any are
missing, stop and tell the user what to install rather than attempting the install.

```powershell
docker --version          # Docker Desktop must be running
python --version          # 3.11 or later
node --version            # 20 LTS or later
npm --version
git --version
```

If Docker Desktop is installed but not running, the user must start it manually.

## 1. Repository skeleton

Create this structure:

```
modernization-platform/
  CLAUDE.md
  .gitignore
  docs/
  docker/
    docker-compose.yml
  backend/
  frontend/
```

`.gitignore` must include at minimum:

```
.venv/
__pycache__/
*.pyc
.env
node_modules/
dist/
.vite/
```

## 2. PostgreSQL container

Create `docker/docker-compose.yml`:

```yaml
services:
  catalog-db:
    image: postgres:17
    container_name: modernization-catalog-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: catalog
      POSTGRES_PASSWORD: catalog_dev_pw
      POSTGRES_DB: modernization_catalog
    ports:
      - "5433:5432"
    volumes:
      - catalog_pgdata17:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U catalog -d modernization_catalog"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  catalog_pgdata17:
```

PostgreSQL 17, the version the client runs. Port **5433** is deliberate — it avoids colliding with any local Postgres already on
5432. The credentials are development-only and are fine to commit in this file: they create the local
container's login. The platform itself reads its login only from `DB_USER` and `DB_PASSWORD` (section 3).

Start it and confirm health:

```powershell
cd docker
docker compose up -d
docker compose ps
cd ..
```

Wait for the container to report healthy before running migrations.

## 3. Backend environment

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

If PowerShell blocks the activation script, tell the user to run this once in an
elevated PowerShell and then retry:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Create `backend/requirements.txt`:

```
fastapi==0.115.*
uvicorn[standard]==0.32.*
sqlalchemy==2.0.*
alembic==1.14.*
psycopg[binary]==3.2.*
pydantic==2.9.*
pydantic-settings==2.6.*
python-dotenv==1.0.*
```

Install:

```powershell
pip install -r requirements.txt
```

Copy `backend/.env.example` (committed) to `backend/.env` (gitignored) and fill it in:

```
DB_HOST=localhost
DB_PORT=5433
DB_NAME=modernization_catalog
DB_SCHEMA=public
DB_USER=catalog
DB_PASSWORD=catalog_dev_pw
RUNS_DIR=D:\ModernizationData\runs
API_HOST=127.0.0.1
API_PORT=8001
CORS_ORIGINS=http://localhost:5174
```

Where the database is (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_SCHEMA`) is configuration. Who connects (`DB_USER`,
`DB_PASSWORD`) comes only from the environment, which this gitignored file may supply. It is never written
anywhere else, never logged, and a connection error never echoes it (section 10). `DATABASE_URL` is no longer
read and is refused.

## 4. Alembic

Alembic reads the connection from the platform's settings (`alembic/env.py`), never from `alembic.ini`. Every
table, sequence and its own `alembic_version` table go into `DB_SCHEMA`, which it creates when missing.

```powershell
alembic init alembic
```

Then generate and apply the first migration once models exist:

```powershell
alembic revision --autogenerate -m "initial catalog schema"
alembic upgrade head
```

## 5. Frontend environment

```powershell
cd ..\frontend
npm create vite@latest . -- --template react-ts
npm install
npm install -D tailwindcss @tailwindcss/postcss postcss autoprefixer
```

Configure Tailwind per the current Tailwind v4 setup for Vite. Verify the build
runs before writing application code.

Create `frontend/.env`:

```
VITE_API_BASE_URL=http://127.0.0.1:8001
```

## 6. Run commands

Three terminals. Document these in the root `README.md`.

```powershell
# Terminal 1 — database
cd docker; docker compose up

# Terminal 2 — backend
cd backend; .\.venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --port 8001

# Terminal 3 — frontend
cd frontend; npm run dev
```

Expected: API docs at `http://127.0.0.1:8001/docs`, UI at `http://localhost:5174`.

Ports **8001** and **5174** are deliberate — 8000 and 5173 are both occupied by
unrelated processes on the dev machine, so the backend binds 8001 and the
frontend binds 5174 instead. Run the frontend with
`npm run dev -- --port 5174 --strictPort`.

## 7. Verification checklist

Before moving on, confirm all of these:

- [ ] `docker compose ps` shows `catalog-db` healthy
- [ ] `alembic upgrade head` completes without error
- [ ] `GET http://127.0.0.1:8001/api/health` returns `{"status":"ok","database":"connected"}`
- [ ] Vite dev server serves the UI shell
- [ ] The UI can reach the API without CORS errors

## 8. .NET SDK (`application-fingerprinting`)

The lifecycle step `application-fingerprinting` (`steps/step-003-fingerprinting/`) is the first step written in
C#/.NET rather than Python — see `21-APPLICATION-FINGERPRINTING.md`. It is invoked via
the `process` adapter, so nothing in the backend depends on the .NET SDK; only
building and running that step directly does.

### Prerequisite

```powershell
dotnet --list-sdks
```

Requires **.NET SDK 10.0.302** (or later within the same feature band — see
`steps/step-003-fingerprinting/global.json`, which pins the exact version with
`rollForward: latestPatch`). An older SDK, or only the .NET 9 SDK, is not enough —
the step targets `net10.0` and its Microsoft.Build.\* / Microsoft.CodeAnalysis.\*
packages are pinned to versions built against .NET 10's bundled MSBuild (18.9.x) and
Roslyn (5.9.x). If `dotnet --list-sdks` does not list `10.0.302` or later, stop and
tell the user to install it rather than attempting the install.

### Build and publish

Always publish before registering or running the step — the `process` adapter
invokes the published executable directly, never `dotnet run` (which recompiles on
every invocation):

```powershell
cd steps\step-003-fingerprinting
dotnet publish src\Fingerprinting.Cli\Fingerprinting.Cli.csproj -c Release -o publish
```

This produces `steps\step-003-fingerprinting\publish\Fingerprinting.Cli.exe`, the
exact path the step's `adapter_config.command` points at, plus the
`schemas\signal-registry-1.0.0.json` and
`schemas\application-fingerprint-1.0.0.schema.json` files it validates against at
runtime (copied alongside the executable via each build).

### Standalone invocation

Per `11-STEP-CONTRACT.md`'s decoupling test:

```powershell
Get-Content sample-context.json | steps\step-003-fingerprinting\publish\Fingerprinting.Cli.exe
```

A developer-convenience mode also exists that bypasses the StepContext/StepResult
envelope entirely, for iterating on extractors without the engine or the database:

```powershell
steps\step-003-fingerprinting\publish\Fingerprinting.Cli.exe `
  --repo D:\path\to\repository `
  --inventory D:\path\to\solution-project-inventory.json `
  --out D:\path\to\output-folder
```

### `.gitignore`

`publish/` and every project's `bin/`/`obj/` are build output, not source, and are
already covered by the root `.gitignore`:

```
bin/
obj/
steps/*/publish/
```

## 9. Standing up a new environment (a new client machine)

The repository alone rebuilds the platform. The database is authoritative for the item
catalog, and the committed export in `catalog/items/` is the catalog's record in git.
**Platform configuration comes from the seed's files. Catalog content comes from the
export.** The factory defaults in `catalog_items.yaml` apply only when there is no export.

1. **Build what the steps run.** Publish the .NET steps (section 8), and create the
   backend and `solution-discovery` virtual environments (section 3).
2. **Start an empty database** (section 2), then migrate it, from `backend/` with the venv
   active:

   ```powershell
   alembic upgrade head
   ```

3. **Seed from the repository:**

   ```powershell
   python -m app.seed
   ```

   It loads, in order:
   1. the legacy patterns;
   2. the lifecycle steps;
   3. every implemented step registration (`steps/*/registration/*.json`,
      `backend/app/steps/*.registration.json`);
   4. the job definitions (`backend/app/jobs/*.yaml`), each activated;
   5. the signal registry and extractors;
   6. **the item catalog from `catalog/items/`**, imported into the empty catalog.

   The seed prints which catalog source it used.
4. **Check that it reproduces the source machine.** On the machine you are copying from,
   with its database live, run:

   ```powershell
   python -m app.seed.reproduce
   ```

   A clean run reports one line counting the historical records it does not reproduce, and
   **0 differences**. Any difference exists only on that machine. Write it into the
   repository before standing up the copy:
   - a step registration file;
   - a job YAML;
   - for the catalog, `python -m app.items.catalog_export export` and commit.
5. **Optionally, prove the export path.** This edits an item in a scratch environment,
   exports it, bootstraps a second one from that export, and checks the edit arrives:

   ```powershell
   python -m app.seed.reproduce --prove-export-bootstrap
   ```

6. **Put run output outside the repository.** Everything a client's work produces — discovery
   runs, verifications, conversion worktrees, experiments
   (`<RUNS_DIR>/<engagement>/experiments/<name>/`) — is written under `RUNS_DIR`. It is required,
   and **a folder inside the repository is refused**: set an absolute folder outside it in
   `backend\.env`, so the repository holds the platform only and can be updated or re-cloned
   without touching client data:

   ```
   RUNS_DIR=D:\ModernizationData\runs
   ```

   Every component reads it through `settings.runs_path`: the workflow engine, the conversion
   runner, the verifier and the experiment commands.
7. **Engagements are client data.** Create them in the UI or API; the seed creates none.
   `scripts/reset-demo.ps1` creates the two demo engagements, and only on a deployment whose
   `.env` sets `DEPLOYMENT=demo`. The default, `client`, refuses: a client's database is the
   only copy of that client's data.

**Reseeding an existing machine** (`python -m app.seed` again) never touches a catalog
that is not empty when an export exists: the database is authoritative. Two explicit
commands bring catalog changes from the repository in, both through the seed baseline so
no UI edit is overwritten:
- `python -m app.items.catalog_export import` merges an export;
- `python -m app.items.catalog_seed` applies changed factory defaults.

## 10. Installing on the client VDI

The platform runs on one machine (CLAUDE.md, "Operating model"), here the client's virtual desktop. It reaches the
client's PostgreSQL 17 server with an ordinary login and the client's package mirrors, and nothing else. Two
commands carry the install: `scripts\preflight.py` reports what the machine has, and `scripts\bootstrap.ps1` sets
everything up.

### What the client provides

1. **A PostgreSQL 17 database and a login for the platform.** Not a superuser, unable to create databases, with
   `CREATE` on that one database: that lets it create the platform's schema and the throwaway schemas verification
   uses, and nothing else. A database administrator runs, for example:

   ```sql
   CREATE ROLE modplatform LOGIN PASSWORD '<chosen by the administrator>' NOSUPERUSER NOCREATEDB NOCREATEROLE;
   CREATE DATABASE modernization OWNER postgres;
   GRANT CONNECT, CREATE, TEMPORARY ON DATABASE modernization TO modplatform;
   ```

   **No extension needs installing.** The migrations create none. `gen_random_uuid()` is built into PostgreSQL 13
   and later, and the triggers are PL/pgSQL, which every database has and any user may use.
2. **Package sources** the VDI can reach: a PyPI mirror, an npm registry, and NuGet feeds for building the step
   programs. The repositories it scans find their NuGet feeds as dotnet does (see "NuGet feeds for scanned
   repositories" below).
3. **Tools on the VDI**, at these versions. Preflight reports anything older as MISSING, with the version needed:

   | Tool | Required | Why this version | Tested with |
   |---|---|---|---|
   | Python | 3.11.0 to 3.13.x | The code is 3.11 syntax. The pinned dependencies (pydantic 2.9, psycopg 3.2) publish builds up to 3.13, so 3.14 is refused | 3.13.14 |
   | Node.js | 20.19.0 or a later 20.x, or 22.12.0 or later | Vite's own requirement (`^20.19.0 \|\| >=22.12.0`); 21.x is refused | 24.13.0 |
   | npm | 7.0.0 or later | The frontend's lockfile is version 3. Every Node.js above ships a newer npm | 11.12.0 |
   | .NET SDK | 10.0.302, or a later 10.0.3xx patch | `steps\step-003-fingerprinting\global.json` pins it, with `rollForward: latestPatch` | 10.0.302 |
   | git | 2.17.0 or later | `git worktree remove`, the newest git command the platform runs | 2.55.0 |

   Also Visual Studio with GitHub Copilot, for running conversions.
4. **Short paths.** Install into a short folder, such as `C:\ModernizationPlatform\code`, and set a short
   `RUNS_DIR`, such as `C:\ModernizationPlatform\runs`. The platform puts each conversion's worktree several
   folders deep under `RUNS_DIR`, beneath the client repository's own deepest path. Windows tools still trip
   over paths longer than 260 characters. Preflight reports, without failing, two settings that lift the limit:
   - **Windows long-path support** (`LongPathsEnabled` under
     `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem`, or the group policy "Enable Win32 long paths"). Only an
     administrator can turn it on.
   - **git's `core.longpaths`.** The account that runs the platform turns it on with
     `git config --global core.longpaths true`.

   Turn both on where the client allows it. Keep the paths short either way.

### Network destinations

The platform contacts only these:

| Destination | Who | When |
|---|---|---|
| The PostgreSQL server (`DB_HOST`:`DB_PORT`) | backend, step programs | always |
| `PIP_INDEX_URL`, `NPM_REGISTRY`, `NUGET_SOURCES` | `bootstrap.ps1` | installing |
| The NuGet feeds each scanned repository resolves (below) | `dependency-assessment` (version lookups, package downloads for API diffs); `dotnet restore` in the package step and the verifier | discovery, preparation, verification |
| nuget.org | `dependency-assessment` | only where no NuGet configuration names a feed, and for the public comparison, which `COMPARE_PUBLIC_NUGET_FEED=false` switches off |

- **Unreachable feeds fail nothing.** A lookup that cannot be answered is recorded as "unknown", never a failure.
- **No telemetry or first-run activity.** The .NET SDK the platform runs sends no usage telemetry, checks for no
  workload update and creates no development certificate (`app.config.QUIET_DOTNET`).
- **The frontend loads nothing external.** It talks only to the backend.
- **Nothing else.** Repositories are registered by local path, and the platform clones nothing.
- **The engine is separate.** GitHub Copilot, run by a person in Visual Studio, talks to GitHub as the company's
  account. That is the engine's traffic, not the platform's.

### NuGet feeds for scanned repositories

A scanned repository's package sources resolve exactly as `dotnet restore` resolves them. That is because
`dependency-assessment` uses NuGet's own configuration loader, and the package step and the verifier run
`dotnet restore` itself. The search order is:
1. every `NuGet.config` from the project's folder up to the repository root;
2. then the folders above the repository, up to the drive root (recorded as declared in `parent`);
3. then the user's `%APPDATA%\NuGet\NuGet.Config` and `%APPDATA%\NuGet\config\*.config`;
4. then the machine-wide files.

`<clear/>` and disabled sources are honoured. Only when none of these names a feed does nuget.org answer, as the
fallback. A local folder declared only machine-wide (Visual Studio's offline packages) is tooling, and is
ignored.

So a repository with no `nuget.config` of its own works when the VDI account's user-level NuGet configuration, or
a `NuGet.config` in a folder above the repositories, names the client's feeds.

**Authenticated feeds** use whatever standard NuGet configuration supplies. The platform never asks for,
stores, logs or records a credential, and a feed URL is recorded without user information. Credentials can come
from:
- `packageSourceCredentials` in a NuGet configuration file, normally the user-level one, written with
  `dotnet nuget update source <name> --username <u> --password <p>`. Add `--store-password-in-clear-text` only
  where the encrypted form cannot be used.
- The environment variable `NuGetPackageSourceCredentials_<source name>`, set to
  `Username=<u>;Password=<p>`.
- A NuGet credential provider, such as the Azure Artifacts Credential Provider or an Artifactory plugin. Install it
  for the account that runs the platform, and sign in once interactively. A step cannot prompt, so it uses
  providers non-interactively.

A feed that answers 401 is recorded per package as "unknown", with the reason; discovery still completes.

### Steps

1. **Clone the repository** into an empty folder, for example `C:\ModernizationPlatform\code`. On a VDI that
   cannot reach the repository, clone from the release bundle instead (below).
2. **Write `backend\.env`** from `backend\.env.example`:

   ```
   DB_HOST=<server>
   DB_PORT=5432
   DB_NAME=modernization
   DB_SCHEMA=modplatform
   RUNS_DIR=C:\ModernizationPlatform\runs
   PIP_INDEX_URL=<the PyPI mirror>
   NPM_REGISTRY=<the npm registry>
   NUGET_SOURCES=<NuGet feed URLs, comma-separated>
   COMPARE_PUBLIC_NUGET_FEED=false
   DEPLOYMENT=client
   ```

   Set `DB_USER` and `DB_PASSWORD` in the environment of the account that runs the platform, or in this same
   gitignored file.
3. **Run preflight** and fix whatever it reports as MISSING:

   ```powershell
   python scripts\preflight.py
   ```

   Before bootstrap it reports the database driver as missing; bootstrap installs it and checks the database
   itself.
4. **Run bootstrap:**

   ```powershell
   .\scripts\bootstrap.ps1
   ```

   It runs eight stages, and each stops with a plain message if it fails:
   1. preflight;
   2. the virtual environment;
   3. Python dependencies;
   4. the database checks;
   5. frontend dependencies;
   6. the six step programs, built and published;
   7. migration into `DB_SCHEMA`;
   8. the seed: platform configuration, and the catalog from the committed export.

   Run it again after an update: each stage brings the machine up to date.
5. **Start the platform**, each in its own terminal:

   ```powershell
   cd backend; .venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --port 8001
   ```

   ```powershell
   cd frontend; npm run dev
   ```

6. **Create the engagement**, either in the UI with **+ New engagement** beside the View selector, or from the
   command line:

   ```powershell
   cd backend; .venv\Scripts\Activate.ps1
   python -m app.engagements.cli create --name "Client A" --target-framework net10.0
   ```

   - `--name` is the client name the UI shows.
   - `--target-framework` is the .NET version the estate moves to, such as `net8.0` or `net10.0`. Every package
     is checked against it.
   - `--id` sets the engagement's id; it defaults to one made from the name (`client-a`).
   - `--target-platform` and `--description` are optional.
   - `python -m app.engagements.cli list` lists the engagements.

   The command checks exactly what the UI checks, and the backend need not be running.
7. **Register a repository** in the UI, under that engagement. The clone URL can be any of:
   - https (`https://host/org/repo.git`);
   - SSH (`git@host:org/repo.git` or `ssh://[user@]host[:port]/org/repo.git`).

   All forms of one repository are the same identity, and the URL is verified against the folder's `origin`
   remote.

   A repository with no remote at all registers without a URL. The form says so plainly, and so does a
   repository whose remote is named something other than `origin`, or is a local folder.

   Discovery runs, and its last step, `conversion-preparation`, prepares the repository's conversion. The
   repository's Conversion section then shows:
   - the worktree and branch;
   - the runbook;
   - the opening message, to copy into GitHub Copilot.

   After the conversion has been run and committed, **Verify** in the same section verifies it.

### Installing from a release bundle

A VDI that cannot reach this repository installs from a git bundle: one file holding a release tag and the full
history behind it.

1. **On a machine with the repository**, write the bundle and its SHA-256:

   ```powershell
   .\scripts\release-bundle.ps1 -Tag rbc-release-1
   ```

   This writes `rbc-release-1.bundle` and `rbc-release-1.bundle.sha256` into a `release` folder beside the
   repository. `-OutDir` chooses another folder.
2. **Copy both files to the VDI** by whatever route the client approves.
3. **Check the hash on the VDI.** The two values must be identical:

   ```powershell
   (Get-FileHash -Algorithm SHA256 .\rbc-release-1.bundle).Hash.ToLower()
   ```

   ```powershell
   Get-Content .\rbc-release-1.bundle.sha256
   ```

4. **Check the bundle and clone it:**

   ```powershell
   git bundle verify .\rbc-release-1.bundle
   ```

   ```powershell
   git clone --branch rbc-release-1 .\rbc-release-1.bundle C:\ModernizationPlatform\code
   ```

   The clone is at the tag, with a detached HEAD. To work on a branch there:

   ```powershell
   git -C C:\ModernizationPlatform\code switch -c rbc-release-1-vdi
   ```

5. Continue from step 2 above: `backend\.env`, preflight, bootstrap.

A later release arrives as a new bundle. Fetch its tag into the existing clone, then check it out:

```powershell
git -C C:\ModernizationPlatform\code fetch <path>\rbc-release-2.bundle "refs/tags/rbc-release-2:refs/tags/rbc-release-2"
```

```powershell
git -C C:\ModernizationPlatform\code checkout rbc-release-2
```

Then run bootstrap again.

### What stays inside the schema

Everything the platform writes is in `DB_SCHEMA`:
- **Its own tables**, through the connection's `search_path`.
- **Scratch work.** The verifier's isolated re-discovery and `python -m app.seed.reproduce` each create a
  throwaway schema in the same database and drop it afterwards. No code creates a database.
- **Resets.** The demo reset (`scripts\reset-demo.ps1`) clears tables only inside the configured schema, and it
  refuses unless `DEPLOYMENT=demo`.

No SQL the platform runs names `public` explicitly. The one exception is the downgrade of an old, already-applied
migration (`e8b3c61f0a94`), which recreates dropped tables as `public.<table>`. It is never run in a forward
install, and applied migrations are never edited (CLAUDE.md rule 4).

