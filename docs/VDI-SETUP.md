# VDI Setup: Modernization Platform

How to set up this codebase (database, backend, frontend and the .NET discovery steps) on a
fresh **Windows** VDI with no developer tools installed.

The versions below come from the repository itself (`backend/requirements.txt`,
`frontend/package.json`, `docker/docker-compose.yml`, `steps/step-003-fingerprinting/global.json`)
and were checked against the development machine where the platform runs today.
`01-ENVIRONMENT-SETUP.md` remains the full developer setup spec; this guide is the
installation checklist for a new machine.

---

## Contents

1. [Choose your path](#1-choose-your-path)
2. [Path A: with Docker](#2-path-a-with-docker)
3. [Path B: without Docker](#3-path-b-without-docker)
4. [Common setup (both paths)](#4-common-setup-both-paths)
5. [Optional: running the sample apps](#5-optional-running-the-sample-apps)
6. [Network and proxy](#6-network-and-proxy)
7. [Final checklist](#7-final-checklist)
8. [Troubleshooting](#8-troubleshooting)

---

## What you end up with

| Component | Runs as | Address |
|---|---|---|
| PostgreSQL 16 | Docker container (Path A) or Windows service (Path B) | `localhost:5433` |
| Backend API (FastAPI) | Your own terminal | http://127.0.0.1:8001 (API docs at `/docs`) |
| Frontend (React + Vite) | Your own terminal | http://localhost:5174 |
| Discovery steps `application-fingerprinting` to `dependency-assessment` (.NET) | Published executables, launched by the backend | — |

Ports **5433**, **8001** and **5174** are deliberate (they avoid the usual defaults). Keep them.

---

## 1. Choose your path

Docker Desktop needs **WSL 2**, which needs **hardware virtualization** inside the VDI
(nested virtualization). Many VDIs do not allow it. Check before installing anything:

```powershell
systeminfo | Select-String "Virtualization|Hyper-V"
```

| What you see | Path |
|---|---|
| "Virtualization Enabled In Firmware: Yes", or "A hypervisor has been detected" | **Path A** is possible |
| "Virtualization Enabled In Firmware: No", or no Hyper-V lines | **Path B** |

Also confirm with your VDI or IT team:

- **Licence:** Docker Desktop needs a paid licence in organisations above Docker's size
  threshold.
- **Admin rights:** needed for Docker Desktop, WSL, PostgreSQL and Git. Python, Node.js and the
  .NET SDK can be installed per user without admin if needed.

If Docker installs but will not start, switch to Path B. Nothing else changes.

---

## 2. Path A: with Docker

PostgreSQL runs in a container, exactly as on the development machine.

### A1. Software to install

| # | Software | Version | Download | Notes |
|---|---|---|---|---|
| 1 | **Git for Windows** | 2.45 or later (dev machine: 2.55.0) | https://git-scm.com/download/win | Defaults are fine. The backend calls `git` directly |
| 2 | **WSL 2** | Latest | `wsl --install --no-distribution` (admin PowerShell), then reboot | Required by Docker Desktop |
| 3 | **Docker Desktop** | 4.x, Engine 27+ and Compose v2 (dev machine: Engine 29.7.2, Compose v5.4.0) | https://www.docker.com/products/docker-desktop/ | Choose the WSL 2 backend. Start it once and wait for "Engine running" |
| 4 | **Python** | **3.11 to 3.14** (tested: 3.13.14 and 3.14.8) | https://www.python.org/downloads/windows/ | Tick **"Add python.exe to PATH"**, or install per user (`01-ENVIRONMENT-SETUP.md` section 10) |
| 5 | **Node.js LTS** | **24.x** (minimum 22.12; dev machine: 24.13.0, npm 11.12.0) | https://nodejs.org/en/download | npm is included |
| 6 | **.NET SDK** | Any **.NET 10** SDK from **10.0.100** (tested: 10.0.203 and 10.0.302) | https://dotnet.microsoft.com/download/dotnet/10.0 | The .NET 9 SDK alone is **not** enough (Part 8). Per user: `01-ENVIRONMENT-SETUP.md` section 10 |

PostgreSQL 16 itself is **not** installed on Windows in this path: Docker pulls the
`postgres:16` image.

### A2. Check the installs

Open a **new** PowerShell window, so the updated PATH is picked up:

```powershell
git --version; docker --version; docker compose version; python --version; node --version; npm --version; dotnet --list-sdks
```

`dotnet --list-sdks` must show a .NET 10 SDK, `10.0.100` or later (any feature band).

### A3. Start the database

From the repository root:

```powershell
cd docker; docker compose up -d; docker compose ps
```

Wait until `catalog-db` shows **healthy**. The container restarts automatically with Docker
Desktop (`restart: unless-stopped`), and its data lives in the `catalog_pgdata` volume.

Then continue with [Part 4](#4-common-setup-both-paths).

---

## 3. Path B: without Docker

Everything, including PostgreSQL, is installed directly on the VDI. The platform behaves
exactly as in Path A; only how the database runs, and one script, differ.

### B1. Software to install

| # | Software | Version | Download | Notes |
|---|---|---|---|---|
| 1 | **Git for Windows** | 2.45 or later (dev machine: 2.55.0) | https://git-scm.com/download/win | Defaults are fine |
| 2 | **PostgreSQL** | **16.x**, latest patch (same major version as the `postgres:16` image) | https://www.postgresql.org/download/windows/ (EDB installer) | See B2 for the installer choices |
| 3 | **Python** | **3.11 to 3.14** | https://www.python.org/downloads/windows/ | Tick **"Add python.exe to PATH"** |
| 4 | **Node.js LTS** | **24.x** (minimum 22.12) | https://nodejs.org/en/download | npm is included |
| 5 | **.NET SDK** | Any **.NET 10** SDK from **10.0.100** | https://dotnet.microsoft.com/download/dotnet/10.0 | |

No Docker and no WSL.

### B2. Install PostgreSQL 16

Run the EDB installer and choose:

| Installer screen | Choose |
|---|---|
| Components | **PostgreSQL Server** and **Command Line Tools**. pgAdmin 4 is optional. Stack Builder is not needed |
| Data directory | Default |
| Password | A password for the `postgres` superuser. Keep it; it is only used in B3 |
| **Port** | **5433** (not the default 5432) |
| Locale | Default |

The installer registers PostgreSQL as a Windows service that starts automatically
(`postgresql-x64-16`).

Add the command-line tools to PATH for your user, so `psql` and `pg_dump` work in new windows:

```powershell
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\Program Files\PostgreSQL\16\bin", "User")
```

### B3. Create the platform's user and database

These are the same values the Docker container creates, so `backend\.env` works unchanged.
Run in a **new** PowerShell window; `psql` asks for the `postgres` password from B2:

```powershell
psql -h localhost -p 5433 -U postgres -c "CREATE ROLE catalog LOGIN PASSWORD 'catalog_dev_pw';"
```
```powershell
psql -h localhost -p 5433 -U postgres -c "CREATE DATABASE modernization_catalog OWNER catalog;"
```

Check that the platform user can connect:

```powershell
psql -h localhost -p 5433 -U catalog -d modernization_catalog -c "SELECT version();"
```

It should report `PostgreSQL 16.x`. No extensions are needed.

### B4. Check the installs

```powershell
git --version; psql --version; python --version; node --version; npm --version; dotnet --list-sdks
```

### B5. What differs from Path A

| Topic | Path B |
|---|---|
| Starting and stopping the database | Windows service: `Start-Service postgresql-x64-16` / `Stop-Service postgresql-x64-16` (admin) |
| `scripts\reset-demo.ps1` | Its pre-reset backup uses `docker exec … pg_dump` and **fails without Docker**. Take the backup yourself, then run the script with `-NoBackup` (below) |
| Restoring a backup | `pg_restore -h localhost -p 5433 -U catalog -d modernization_catalog --clean <file>` |
| `docker\docker-compose.yml` | Not used |

Backup before a demo reset (write it **outside** the repository):

```powershell
pg_dump -h localhost -p 5433 -U catalog -d modernization_catalog -Fc -f "$env:USERPROFILE\catalog-backup.dump"
```
```powershell
.\scripts\reset-demo.ps1 -NoBackup
```

Then continue with [Part 4](#4-common-setup-both-paths).

---

## 4. Common setup (both paths)

All commands run from the **repository root** unless they start with `cd`.

### 4.1 Get the code

```powershell
git clone <repository-url> modernization-platform
```

`.env` files, `.venv`, `node_modules` and the steps' `publish` folders are **not** in git.
Steps 4.2–4.6 create them.

### 4.2 Backend

Create the virtual environment and install the Python packages (FastAPI 0.115,
SQLAlchemy 2.0, Alembic 1.14, psycopg 3.2, Pydantic 2.12):

```powershell
cd backend; python -m venv .venv; .\.venv\Scripts\Activate.ps1; python -m pip install --upgrade pip; pip install -r requirements.txt
```

If activation is blocked by the execution policy, run this once and retry:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Create `backend\.env` from the committed example. The defaults match both Path A and Path B:

```powershell
cd backend; Copy-Item .env.example .env
```

| Key | Value | Meaning |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://catalog:catalog_dev_pw@localhost:5433/modernization_catalog` | The database from Part 2 or 3 |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8001` | |
| `CORS_ORIGINS` | `http://localhost:5174,http://127.0.0.1:5174` | The frontend's address |
| `RUNS_DIR` | `./runs` | Where step runs write their output |

Create the schema and load the catalog:

```powershell
cd backend; .\.venv\Scripts\Activate.ps1; alembic upgrade head; python -m app.seed
```

The seed is idempotent and creates no engagements.

### 4.3 Frontend

```powershell
cd frontend; npm install
```

**`frontend\.env` is not in git and has no example file.** Create it:

```powershell
cd frontend; Set-Content -Path .env -Value "VITE_API_BASE_URL=http://127.0.0.1:8001" -Encoding utf8
```

### 4.4 Discovery steps (.NET)

`application-fingerprinting`, `entry-point-inventory`, `outbound-invocation-inventory` and
`dependency-assessment` run as **published** executables at fixed paths
(`steps\step-003-fingerprinting\registration\*.json`). Build output is not in git, so publish
all four on the VDI:

```powershell
cd steps\step-003-fingerprinting; dotnet publish src\Fingerprinting.Cli\Fingerprinting.Cli.csproj -c Release -o publish
```
```powershell
cd steps\step-003-fingerprinting; dotnet publish src\Fingerprinting.EntryPoints.Cli\Fingerprinting.EntryPoints.Cli.csproj -c Release -o publish\entry-point-inventory
```
```powershell
cd steps\step-003-fingerprinting; dotnet publish src\Fingerprinting.Outbound.Cli\Fingerprinting.Outbound.Cli.csproj -c Release -o publish\outbound-invocation-inventory
```
```powershell
cd steps\step-003-fingerprinting; dotnet publish src\Fingerprinting.Dependencies.Cli\Fingerprinting.Dependencies.Cli.csproj -c Release -o publish\dependency-assessment
```

| Step | Executable the platform launches |
|---|---|
| `application-fingerprinting` | `publish\Fingerprinting.Cli.exe` |
| `entry-point-inventory` | `publish\entry-point-inventory\EntryPointInventory.Cli.exe` |
| `outbound-invocation-inventory` | `publish\outbound-invocation-inventory\OutboundInvocationInventory.Cli.exe` |
| `dependency-assessment` | `publish\dependency-assessment\DependencyAssessment.Cli.exe` |

`repository-ingest`, `solution-discovery`, `item-detection` and `dependency-and-context-map` are Python and run inside the backend; nothing to publish. Republish
after any change under `steps\step-003-fingerprinting\src\`, then restart the backend.

### 4.5 Start the platform

Two terminals, left open so you can read their logs. Do not start them as background
processes.

**Terminal 1, backend:**

```powershell
cd backend; .\.venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --port 8001
```

**Terminal 2, frontend:**

```powershell
cd frontend; npm run dev -- --port 5174 --strictPort
```

Open http://localhost:5174. The API docs are at http://127.0.0.1:8001/docs.

### 4.6 Run the tests (optional)

```powershell
cd backend; .\.venv\Scripts\Activate.ps1; python -m unittest discover -s tests
```
```powershell
cd steps\step-003-fingerprinting; dotnet test
```

---

## 5. Optional: running the sample apps

**Not needed for the platform.** The platform scans the sample apps without building them.
Install these only to build and run the samples themselves (`sampleapps\`). Same for both
paths.

| Software | Version | Needed for |
|---|---|---|
| .NET Framework 4.8 / 4.8.1 runtime | Built into Windows 11 | Running the `net472` samples |
| **.NET Framework 4.7.2 Developer Pack** | 4.7.2 | `sampleapps\WCF`, `sampleapps\WCF-backend` |
| .NET Framework 4.6.1, 4.7, 4.7.1 targeting packs | as listed | `sampleapps\eShopModernizing` |
| **.NET 8 SDK** | 8.0.x | `sampleapps\.NetCoreUpgrade` (its `global.json` pins 8.0.x), `eShopOnWeb` |
| .NET 6 runtime + Windows Desktop runtime 6 | 6.0.x | Running `legacy-grpc-suite` and eShopModernizing's `net6.0-windows` project |
| **IIS Express 10** | 10.0 | Hosting the ASMX backend (`WCF-backend\scripts\Start-FundsTransferWS.ps1`) without admin |
| Windows SDK .NET Framework tools (`SvcUtil.exe`) | NETFX 4.8 tools | Only for regenerating the WCF service-reference proxy |

The .NET Framework developer packs and targeting packs are at
https://dotnet.microsoft.com/download/dotnet-framework.

**Recommended editor:** VS Code, or Visual Studio 2022 17.14+ if the team wants a full IDE.

---

## 6. Network and proxy

Setup and the platform itself download from these hosts:

| Host | Used by | When |
|---|---|---|
| `pypi.org`, `files.pythonhosted.org` | `pip install` | Setup |
| `registry.npmjs.org` | `npm install` | Setup |
| `api.nuget.org` | `dotnet publish` / restore | Setup |
| `registry-1.docker.io` (Docker Hub) | `docker compose up` (Path A only) | Setup |
| NuGet feeds (nuget.org, or the client's Artifactory) | `dependency-assessment` | **Every run** of `dependency-assessment` |

If the VDI only reaches the internet through a corporate proxy or an Artifactory mirror,
configure each tool:

| Tool | How |
|---|---|
| pip | `pip config set global.index-url <mirror-url>`, or the `HTTPS_PROXY` environment variable |
| npm | `npm config set registry <mirror-url>`, or `npm config set proxy` / `https-proxy` |
| NuGet / dotnet | A `NuGet.Config` with the mirror as a package source (`dotnet nuget add source <url> -n mirror`) |
| Docker | Docker Desktop → Settings → Resources → Proxies, or a registry mirror |

---

## 7. Final checklist

- [ ] Versions confirmed: Git 2.45+, Python 3.11 to 3.14, Node 24, a .NET 10 SDK (10.0.100+) (plus Docker on Path A, `psql` 16 on Path B)
- [ ] Database reachable on `localhost:5433` as `catalog` / `modernization_catalog`
- [ ] `backend\.env` created from `.env.example`
- [ ] `alembic upgrade head` and `python -m app.seed` completed without errors
- [ ] `frontend\.env` created with `VITE_API_BASE_URL=http://127.0.0.1:8001`
- [ ] All four step executables exist under `steps\step-003-fingerprinting\publish\`
- [ ] http://127.0.0.1:8001/docs loads
- [ ] http://localhost:5174 loads with no CORS errors in the browser console
- [ ] (Path B) A `pg_dump` backup works before you rely on `reset-demo.ps1`

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Docker Desktop: "WSL 2 installation is incomplete" or "Virtualization support not detected" | No nested virtualization on the VDI | Use **Path B** |
| `.\.venv\Scripts\Activate.ps1` cannot be loaded | Execution policy | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `dotnet publish` fails with a `global.json` SDK error | Only the .NET 9 SDK is installed | Install any .NET 10 SDK, 10.0.100 or later |
| A step fails at once, "You must install .NET to run this application" | The .NET SDK is installed per user, and `DOTNET_ROOT` is not set | Set `DOTNET_ROOT` to the SDK's folder for the account (`01-ENVIRONMENT-SETUP.md` section 10); preflight checks it |
| Backend starts but uses the wrong database or run folder | Started from the repository root instead of `backend\` | `.env` and `RUNS_DIR` are relative: always start from `backend\` |
| UI loads but every request fails | Missing `frontend\.env`, or the frontend is not on port 5174 (CORS) | Create `frontend\.env` (4.3); start with `--port 5174 --strictPort` |
| `connection refused` on port 5433 | Database not running, or Path B installed on port 5432 | Path A: `docker compose ps`. Path B: check the service, and the port in `C:\Program Files\PostgreSQL\16\data\postgresql.conf` |
| A step fails with "executable not found" | Step not published, or published to a different folder | Republish to the exact folders in 4.4 |
| `pip`, `npm` or `dotnet` restore times out | Proxy or mirror not configured | Part 6 |
