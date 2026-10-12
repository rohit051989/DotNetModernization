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
    image: postgres:16
    container_name: modernization-catalog-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: catalog
      POSTGRES_PASSWORD: catalog_dev_pw
      POSTGRES_DB: modernization_catalog
    ports:
      - "5433:5432"
    volumes:
      - catalog_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U catalog -d modernization_catalog"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  catalog_pgdata:
```

Port **5433** is deliberate — it avoids colliding with any local Postgres already on
5432. The credentials are development-only and are fine to commit in this file.

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

Create `backend/.env.example` (committed) and `backend/.env` (gitignored, same
contents for local dev):

```
DATABASE_URL=postgresql+psycopg://catalog:catalog_dev_pw@localhost:5433/modernization_catalog
API_HOST=127.0.0.1
API_PORT=8001
CORS_ORIGINS=http://localhost:5174
```

## 4. Alembic

Initialise Alembic inside `backend/`, configure it to read `DATABASE_URL` from the
environment rather than hardcoding it in `alembic.ini`, and point its target
metadata at the SQLAlchemy models.

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

6. **Engagements are client data.** Create them in the UI or API; the seed creates none.
   `scripts/reset-demo.ps1` creates the two demo engagements, and only on a deployment whose
   `.env` sets `DEPLOYMENT=demo`. The default, `client`, refuses: a client's database is the
   only copy of that client's data.

**Reseeding an existing machine** (`python -m app.seed` again) never touches a catalog
that is not empty when an export exists: the database is authoritative. Two explicit
commands bring catalog changes from the repository in, both through the seed baseline so
no UI edit is overwritten:
- `python -m app.items.catalog_export import` merges an export;
- `python -m app.items.catalog_seed` applies changed factory defaults.
