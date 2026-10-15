# Installing the Modernization Platform on the client VDI

This is the complete guide for installing the platform on the client's Windows virtual desktop (VDI). It is written
for someone doing it for the first time, with nobody to ask. Follow the sections in order. Every command is
PowerShell, run in an ordinary (not administrator) PowerShell window.

The platform runs on this one machine, for one person (`CLAUDE.md`, "Operating model"): the backend, the frontend,
the step programs, and the repositories it scans all live here; the database is the client's PostgreSQL server.

Reference material this guide points to, in `01-ENVIRONMENT-SETUP.md` section 10: the full list of network
destinations, how NuGet feeds resolve for scanned repositories, and what stays inside the platform's database
schema.

| Section | |
|---|---|
| [A. Before starting](#a-before-starting) | versions, access, short paths |
| [B. Placing the code](#b-placing-the-code) | copy the folder, "dubious ownership" |
| [C. Account settings](#c-account-settings-no-administrator-rights) | core.longpaths, DOTNET_ROOT, PATH |
| [D. Package sources](#d-package-sources) | finding pip, npm and NuGet addresses |
| [E. Database](#e-database) | schema name, rights |
| [F. backend\.env](#f-backendenv) | every key |
| [G. Preflight](#g-preflight) | running it, fixing each MISSING |
| [H. Bootstrap](#h-bootstrap) | stage by stage |
| [I. Starting the platform](#i-starting-the-backend-and-the-frontend) | commands, ports |
| [J. Creating the engagement](#j-creating-the-engagement) | UI or command |
| [K. Registering a client repository](#k-cloning-and-registering-a-client-repository) | what discovery produces |
| [L. Troubleshooting](#l-troubleshooting) | |
| [M. Stopping, restarting, a later release](#m-stopping-restarting-and-installing-a-later-release) | |

---

## A. Before starting

### Required versions

Install these first. None needs administrator rights if installed per user (section C shows how for Python and
.NET). Preflight (section G) checks every one and says exactly what is wrong.

| Tool | Version needed | Notes |
|---|---|---|
| **Python** | **3.11 to 3.14** (tested: 3.13.14 and 3.14.8) | Every dependency installs from a prebuilt wheel, so no compiler is needed. 3.15 is refused |
| **Node.js** | **20.19.0 or a later 20.x, or 22.12.0 or later** (tested: 24.13.0) | 21.x is refused. npm comes with it |
| **npm** | **7.0.0 or later** | Every Node.js above ships a newer one |
| **.NET SDK** | **any .NET 10 SDK, 10.0.100 or later** (tested: 10.0.203 and 10.0.302) | Any feature band (1xx, 2xx, 3xx). The .NET 9 SDK alone is not enough |
| **git** | **2.17.0 or later** (tested: 2.55.0) | |
| Visual Studio with GitHub Copilot | the client's standard | Only for running a conversion (section K); the platform does not need it |

### Access needed

Ask for these before you start:

- **An account on the VDI.** No administrator rights are needed.
- **A folder you can write to, with a short path**, such as `C:\MP` or `D:\MP`. The rest of this guide uses
  `C:\MP\code` for the platform and `C:\MP\runs` for its output.
- **A PostgreSQL 17 database and a login for the platform**, from the client's database administrator. Section E
  gives them the exact request.
- **Package mirrors the VDI can reach:** one each for Python (pip), npm and NuGet, or direct access to pypi.org,
  registry.npmjs.org and nuget.org. Section D shows how to find what works.
- **Read access to the client's git server**, to clone the repositories you will scan, and the NuGet feeds those
  repositories use.

### Why paths must be short

Windows tools fail on file paths longer than 260 characters, and git refuses to write a path longer than 259
characters unless `core.longpaths` is on. The platform's own longest file is 159 characters, so its folder must
be shorter than 99 characters. Each conversion is a full copy of a client repository placed several folders deep
under the run folder, beneath the repository's own deepest path. Keep both short:

| Use | Example | Avoid |
|---|---|---|
| Platform folder | `C:\MP\code` | `C:\Users\firstname.lastname\Documents\Projects\Client\Modernization Platform\code` |
| Run folder (`RUNS_DIR`) | `C:\MP\runs` | anything inside the platform folder (refused) |
| Client repositories | `C:\MP\repos\OrderService` | a deep project-share path |

Section C turns `core.longpaths` on for your account as well.

---

## B. Placing the code

The platform arrives as a folder (for example on a share, or in a zip). Copy **the whole folder, including the
hidden `.git` folder**, to the short path. `.git` is what lets you install a later release in place (section M).

```powershell
robocopy \\share\delivery\modernization-platform C:\MP\code /E
```

Check that `.git` came across, and that git can read it:

```powershell
git -C C:\MP\code log -1 --format="%h %d %s"
```

It prints the release commit and its tag, for example `0a23420 (HEAD, tag: rbc-release-1) ...`.

If the release came instead as a git bundle (`rbc-release-1.bundle` with `rbc-release-1.bundle.sha256` beside
it), check its hash as in section M, then clone it; git warns that the tag "is not a commit", which is expected:

```powershell
git clone -c core.longpaths=true --branch rbc-release-1 .\rbc-release-1.bundle C:\MP\code
```

### "detected dubious ownership"

If instead git prints:

```
fatal: detected dubious ownership in repository at 'C:/MP/code'
'C:/MP/code' is owned by:
        BUILTIN/Administrators (S-1-5-32-544)
but the current user is:
        CORP/jdoe (S-1-5-21-...)
To add an exception for this directory, call:

        git config --global --add safe.directory C:/MP/code
```

the copy kept the original owner (another account, or Administrators), and git will not work in a repository it
does not consider yours. Tell git this one folder is safe, for your account only, with exactly the command it
printed (forward slashes):

```powershell
git config --global --add safe.directory C:/MP/code
```

Then run the `git log` check again. Do the same for any client repository that shows the error (section K). Do
not use `safe.directory '*'`: it switches the check off for every folder.

If the PowerShell scripts will not run ("running scripts is disabled on this system", or "is not digitally
signed"), the copy kept Windows' downloaded-file mark. Clear it for this folder only:

```powershell
Get-ChildItem C:\MP\code -Recurse -File | Unblock-File
```

The commands in this guide start the scripts with `powershell -ExecutionPolicy Bypass -File ...`, which works
without changing any policy.

---

## C. Account settings (no administrator rights)

All of these are settings for your account only. Open a **new** PowerShell window after changing any of them.

### git long paths

```powershell
git config --global core.longpaths true
```

### Python, installed per user

If the client provides Python, skip this. Otherwise, for example Python 3.14 into `C:\MP\tools\python314`:

```powershell
.\python-3.14.8-amd64.exe /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 TargetDir=C:\MP\tools\python314
```

Nothing else is needed: you give bootstrap this Python's full path (section H).

### .NET installed per user: DOTNET_ROOT and PATH

If the client provides the .NET SDK machine-wide (in `C:\Program Files\dotnet`), skip this. Otherwise install it
with Microsoft's script into its own folder, for example 10.0.203:

```powershell
powershell -ExecutionPolicy Bypass -File .\dotnet-install.ps1 -Version 10.0.203 -InstallDir C:\MP\tools\dotnet -NoPath
```

Then set two account settings. The platform's step programs find a per-user .NET **only** through `DOTNET_ROOT`;
without it every discovery step fails at once with "You must install .NET to run this application". And the
platform runs `dotnet` itself, so it must be on `PATH`:

```powershell
[Environment]::SetEnvironmentVariable('DOTNET_ROOT', 'C:\MP\tools\dotnet', 'User')
```

```powershell
[Environment]::SetEnvironmentVariable('Path', 'C:\MP\tools\dotnet;' + [Environment]::GetEnvironmentVariable('Path', 'User'), 'User')
```

Open a new window and check:

```powershell
dotnet --list-sdks
```

It lists `10.0.203 [C:\MP\tools\dotnet\sdk]`. If it lists only SDKs in `C:\Program Files\dotnet`, a machine-wide
.NET comes first on the machine's `PATH`; that is fine as long as it is a .NET 10 SDK, and preflight will say so.

---

## D. Package sources

Bootstrap installs the platform's own dependencies: Python packages with pip, the frontend's with npm, and the
NuGet packages the step programs are built from. Each tool needs an address it can reach. Find working ones before
you write `backend\.env`.

### What the machine already uses

Other teams on the VDI usually have these configured already. Ask each tool:

```powershell
py -m pip config list
```

```powershell
npm config get registry
```

```powershell
dotnet nuget list source
```

Typical answers on a client network are Artifactory or Nexus addresses such as
`https://artifactory.client.com/artifactory/api/pypi/pypi-remote/simple`,
`https://artifactory.client.com/artifactory/api/npm/npm-remote/` and
`https://artifactory.client.com/artifactory/api/nuget/v3/nuget-remote/index.json`.

### From a client repository's nuget.config

A client repository usually names the client's NuGet feeds in a `nuget.config` at its root (or in a parent
folder). Open it and look under `<packageSources>`:

```xml
<packageSources>
  <clear />
  <add key="client-nuget" value="https://artifactory.client.com/artifactory/api/nuget/v3/nuget-remote/index.json" />
</packageSources>
```

A feed that mirrors nuget.org (it is usually called "remote", "proxy" or "nuget-org") is what the step programs
need. A feed of the client's own internal packages is not.

### Checking an address works

```powershell
Invoke-WebRequest -UseBasicParsing https://artifactory.client.com/artifactory/api/nuget/v3/nuget-remote/index.json | Select-Object StatusCode
```

`200` means it works. `401` means it works but needs a login (below). An error such as "The remote name could not
be resolved" or a timeout means this machine cannot reach it: ask for another address.

### Where each one goes

| Tool | Setting in `backend\.env` | If it needs a login |
|---|---|---|
| pip | `PIP_INDEX_URL` (the address ending in `/simple`) | Leave `PIP_INDEX_URL` empty and put the address with its login in your pip configuration: `py -m pip config set global.index-url https://user:token@host/.../simple` |
| npm | `NPM_REGISTRY` | Leave it empty and set the registry and its token with `npm config set registry ...` and `npm login`, or as the client's standard `.npmrc` says |
| NuGet | `NUGET_SOURCES` (comma-separated if several) | Leave it empty and add the feed with its login to your account's NuGet configuration: `dotnet nuget add source <address> -n client-nuget -u <user> -p <token>` |

When a setting is empty, bootstrap lets the tool use its own configuration, and preflight checks that
configuration (it says "from pip configuration", "from npm configuration" or "from NuGet configuration"). When the
tool has no configuration either, the public sites are used.

Also set `COMPARE_PUBLIC_NUGET_FEED=false` in `backend\.env` when nuget.org is not reachable (section F).

The repositories you scan bring their own `nuget.config`; you configure nothing for them. If their feeds need a
login, the same account NuGet configuration (or a credential provider, such as Azure Artifacts') supplies it, and
the platform never sees or stores it. `01-ENVIRONMENT-SETUP.md` section 10, "NuGet feeds for scanned
repositories", has the details.

---

## E. Database

The client's database administrator creates one database and one login for the platform. Send them this, with
the names filled in:

```sql
CREATE ROLE modplatform LOGIN PASSWORD '<chosen by the administrator>' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE DATABASE modernization OWNER postgres;
GRANT CONNECT, CREATE, TEMPORARY ON DATABASE modernization TO modplatform;
```

| Right | Why |
|---|---|
| `CONNECT` | to connect |
| `CREATE` on the database | to create the platform's own schema, and the throwaway schemas verification creates and drops |
| `TEMPORARY` | temporary tables during migrations |
| superuser, `CREATEDB`, `CREATEROLE` | **not** needed, and not wanted |

No PostgreSQL extension is needed. The server must be **PostgreSQL 17**.

### The schema name

The platform creates its own schema in that database (`DB_SCHEMA`, section F) and keeps every table in it. The
name must be:

- **lowercase** letters, digits and underscores only;
- starting with a letter or an underscore;
- at most 63 characters;
- **no hyphens, spaces or capitals.** `modplatform` and `mod_platform` are fine; `mod-platform` and `ModPlatform`
  are refused.

If the administrator creates the schema for you instead, they must make your login its owner, or grant it
`CREATE` and `USAGE` on it.

---

## F. backend\.env

Create it from the committed example:

```powershell
Copy-Item C:\MP\code\backend\.env.example C:\MP\code\backend\.env
```

```powershell
notepad C:\MP\code\backend\.env
```

`backend\.env` is never committed and never copied anywhere by the platform. Every key:

| Key | Meaning | Example | Secret |
|---|---|---|---|
| `DB_HOST` | The PostgreSQL server | `pgsql01.client.com` | no |
| `DB_PORT` | Its port | `5432` | no |
| `DB_NAME` | The database from section E | `modernization` | no |
| `DB_SCHEMA` | The platform's schema (section E naming rules) | `modplatform` | no |
| `DB_USER` | The login from section E | `modplatform` | **yes** |
| `DB_PASSWORD` | Its password | (from the administrator) | **yes** |
| `RUNS_DIR` | Where all run output, worktrees, conversions and verifications go. Absolute, short, **outside** the platform folder | `C:\MP\runs` | no |
| `API_HOST` | The address the backend listens on | `127.0.0.1` | no |
| `API_PORT` | Its port. Bootstrap writes the frontend's link to the backend from this | `8001` | no |
| `CORS_ORIGINS` | The frontend's address(es), comma-separated | `http://localhost:5174,http://127.0.0.1:5174` | no |
| `DEPLOYMENT` | `client`. **Never set it to `demo` on the VDI**: `demo` lets the demo-reset script delete every engagement and repository, and this database is the only copy of the client's data | `client` | no |
| `PIP_INDEX_URL` | Section D; empty to use pip's own configuration | `https://artifactory.client.com/artifactory/api/pypi/pypi-remote/simple` | no (put a login in pip's own configuration, not here) |
| `NPM_REGISTRY` | Section D; empty to use npm's own configuration | `https://artifactory.client.com/artifactory/api/npm/npm-remote/` | no |
| `NUGET_SOURCES` | Section D; feed addresses or folders for building the step programs, comma-separated; empty to use the account's NuGet configuration | `https://artifactory.client.com/artifactory/api/nuget/v3/nuget-remote/index.json` | no |
| `COMPARE_PUBLIC_NUGET_FEED` | Whether dependency assessment also asks nuget.org which versions exist publicly. `false` where nuget.org is unreachable | `false` | no |

`DB_USER` and `DB_PASSWORD` may instead be set as account environment variables, and then left out of the file.
The platform never writes them anywhere else, never logs them, and removes them from any error message. Do not
set `DATABASE_URL`: it is refused.

A filled-in example:

```
DB_HOST=pgsql01.client.com
DB_PORT=5432
DB_NAME=modernization
DB_SCHEMA=modplatform
DB_USER=modplatform
DB_PASSWORD=<from the administrator>
RUNS_DIR=C:\MP\runs
API_HOST=127.0.0.1
API_PORT=8001
CORS_ORIGINS=http://localhost:5174,http://127.0.0.1:5174
DEPLOYMENT=client
PIP_INDEX_URL=
NPM_REGISTRY=
NUGET_SOURCES=
COMPARE_PUBLIC_NUGET_FEED=false
```

---

## G. Preflight

Preflight checks everything this guide has set up and changes nothing. Run it with the Python you will use:

```powershell
cd C:\MP\code; C:\MP\tools\python314\python.exe scripts\preflight.py
```

(`py -3 scripts\preflight.py` if Python is installed with the launcher.)

### Reading it

Each line is `PRESENT` or `MISSING`, with what was found and what is needed. The last line counts them:

```
Tools
  PRESENT  Python: 3.14.8 (3.11.0 to 3.14.x needed)
  PRESENT  .NET SDK: 10.0.203 (any .NET 10 SDK from 10.0.100 needed, steps\step-003-fingerprinting\global.json)
  MISSING  .NET runtime for the step programs: dotnet comes from C:\MP\tools\dotnet, but DOTNET_ROOT is not set ...
...
9 present, 1 missing: .NET runtime for the step programs
```

The "Long paths" lines are `ON` or `OFF` and never fail. Before bootstrap, the database section reports the
database driver as missing: that is expected, bootstrap installs it.

### Fixing each MISSING item

| MISSING | Fix |
|---|---|
| Python ... too old / too new | Install a Python 3.11 to 3.14 (section C), and run preflight and bootstrap with its full path |
| Node.js ... too old | Install Node.js 22.12 or later (or 20.19+) |
| npm ... too old | Comes with Node.js: update Node.js |
| .NET SDK: none of ... | Install a .NET 10 SDK (section C). A .NET 9 or a preview SDK does not count |
| .NET runtime for the step programs ... DOTNET_ROOT is not set | Set `DOTNET_ROOT` to the folder it names (section C), open a new window |
| git ... too old / not found | Install git 2.17 or later, and open a new window |
| PIP_INDEX_URL / NPM_REGISTRY / NUGET_SOURCES ... unreachable | This machine cannot reach that address: find one it can (section D) |
| ... HTTP 404 | The address is wrong (often a missing `/simple` for pip, or `/index.json` for NuGet) |
| RUNS_DIR: not set / inside the repository / not writable | Set an absolute folder outside `C:\MP\code` that you can write to (section F) |
| connection: ... | Check `DB_HOST`, `DB_PORT`, `DB_NAME`; a "password authentication failed" means `DB_USER` / `DB_PASSWORD`; a timeout means the VDI cannot reach the server (a firewall) |
| connection: ... (17 needed) | The server is not PostgreSQL 17: ask the administrator |
| schema ...: this login cannot create a schema | The login lacks `CREATE` on the database (section E) |
| schema ...: exists, but this login cannot create tables in it | Ask the administrator to make the login the schema's owner |
| scratch schemas | The login lacks `CREATE` on the database (section E) |

---

## H. Bootstrap

Bootstrap installs and sets up everything, in eight stages. Run it with the Python you chose:

```powershell
cd C:\MP\code; powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -Python C:\MP\tools\python314\python.exe
```

(Without `-Python` it uses `py -3`, else `python`.)

**It is safe to run again at any time.** Each stage skips work already done: a second run takes seconds. To run
one stage only, add `-Stage <n>`; to make a stage redo its work even when it looks up to date, add `-Force`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -Python C:\MP\tools\python314\python.exe -Stage 6 -Force
```

When a stage fails, bootstrap prints `Stage <n> failed: <reason>` in red, does nothing after it, and names the
command to rerun just that stage once you have fixed the cause. Times below are for a first run; reruns skip.

| Stage | What it does | First run | Skipped when |
|---|---|---|---|
| **1. Preflight** | Section G without the database checks | under a minute | never (it only reads) |
| **2. Python virtual environment** | Creates `backend\.venv` with the Python you gave | under a minute | `backend\.venv` exists. To rebuild it with another Python, delete the folder and rerun |
| **3. Python dependencies** | Installs `backend\requirements.txt` into `backend\.venv`, from wheels only (`--only-binary=:all:`), so nothing is compiled | 1 to 3 minutes | `requirements.txt`, `PIP_INDEX_URL` and the Python are unchanged since the last install |
| **4. Preflight: the database** | Section G's database checks: connection, PostgreSQL 17, the right to create the schema and scratch schemas | seconds | never (it only reads) |
| **5. Frontend** | Writes `frontend\.env` (the backend's address, from `API_HOST` and `API_PORT`) if missing; installs the frontend's packages with `npm ci` | 1 to 2 minutes | `package-lock.json` and `NPM_REGISTRY` unchanged |
| **6. C# step programs** | Builds and publishes the six discovery programs into `steps\step-003-fingerprinting\publish\` with your .NET SDK | 3 to 10 minutes (the first restore downloads the build packages) | for each program: its sources, the SDK version and `NUGET_SOURCES` unchanged |
| **7. Migration** | Creates or updates every table in `DB_SCHEMA` (`alembic upgrade head`) | under a minute | nothing to do when already up to date |
| **8. Seed** | Loads the platform's configuration and the item catalog | under a minute | it changes only what changed, and never overwrites catalog edits made in the UI |

What failure looks like, and what to do:

| Stage | Failure | Usual cause |
|---|---|---|
| 1, 4 | `a prerequisite is missing (listed above as MISSING)` | Section G's table |
| 2 | `could not create backend\.venv` | The `-Python` path is wrong |
| 3 | `pip could not install ... from wheels` | The mirror is unreachable or needs a login (section D); "No matching distribution found" means the mirror lacks a package or a wheel for this Python (section L) |
| 5 | `npm ci failed` | The registry is unreachable or needs a login (section D) |
| 6 | `dotnet publish of <program> failed` | NuGet feed unreachable or needing a login (section D), or no .NET 10 SDK. Run the command it prints to see the error |
| 7 | `alembic upgrade head failed` | The database login lost a right, or the schema belongs to another login |
| 8 | `python -m app.seed failed` | Read the message above it; rerun with `-Stage 8` |

**Everything else runs inside the backend's one Python environment.** Conversion preparation, verification, and
the vendored scripts under `third_party\code-modernization` are part of the backend and use `backend\.venv`.
Nothing needs installing separately for them, and there is no second Python environment to look after.

At the end bootstrap prints `Bootstrap complete` and the two commands of section I.

---

## I. Starting the backend and the frontend

Two PowerShell windows, each left open: they show the logs. Do not start them in the background.

**Window 1, the backend** (port 8001, `API_PORT`):

```powershell
cd C:\MP\code\backend; .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

It is up when it prints `Application startup complete.` and `Uvicorn running on http://127.0.0.1:8001`. Check it
from a third window:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/health
```

It answers `status: ok` and `database: connected`.

Do not add `--reload` on the VDI: it restarts the backend whenever a file changes, which stops any discovery or
verification in progress.

**Window 2, the frontend** (port 5174, which `CORS_ORIGINS` names):

```powershell
cd C:\MP\code\frontend; npm run dev -- --port 5174 --strictPort
```

It is up when it prints `Local: http://localhost:5174/`. Open that address in the browser: the header shows
**Modernization Platform** with a green **connected** badge. A red **unreachable** badge means the backend is not
running, or `frontend\.env` points at another port.

---

## J. Creating the engagement

An engagement is one client program. Create it once, either way:

- **In the UI:** **+ New engagement**, beside the **View** selector at the top right. Fill in the client name and
  the target framework (the .NET version the estate moves to, such as `net10.0`); the id is filled in from the
  name. **Create engagement**, and the view switches to it.
- **From the command line** (the backend need not be running):

  ```powershell
  cd C:\MP\code\backend; .venv\Scripts\python.exe -m app.engagements.cli create --name "Client A" --target-framework net10.0
  ```

  `--id` sets the id (default: made from the name, `client-a`); `--target-platform` and `--description` are
  optional. `python -m app.engagements.cli list` lists the engagements.

---

## K. Cloning and registering a client repository

### Clone to a short path

```powershell
git clone -c core.longpaths=true https://git.client.com/team/OrderService.git C:\MP\repos\OrderService
```

If the repository's `nuget.config` names a feed by a relative folder (for example `..\EnterprisePackages\feed`),
place that folder beside it as well, exactly where the path points.

If git reports "dubious ownership" for a repository you copied rather than cloned, see section B.

### Register it

In the UI, choose the engagement in **View**, then **Repositories** → **+ Register Repository**:

1. **Local folder path:** `C:\MP\repos\OrderService`, then leave the field. The form inspects the folder and fills
   in the clone URL from its `origin` remote. https and SSH (`git@host:org/repo.git`, `ssh://...`) are both fine.
   A repository with no remote at all registers without one; the form says so.
2. **Register & launch discovery.**

### What discovery and preparation produce

Discovery runs every step on its own, and its last step, `conversion-preparation`, prepares the first conversion.
It takes from a few minutes to much longer for a large repository; the repository's page shows each step as it
finishes (**Executions** tab).

In the UI, on the repository's page:

| Tab | Shows |
|---|---|
| Overview | size, projects, entry points, items found |
| Surface | what can call the repository, and what it calls |
| Structure & fingerprint | solutions, projects, frameworks |
| Dependencies | every package: current, recommended version, outcome, deprecated or vulnerable |
| Work list | the catalog items found, where, and how each is to be resolved |
| Tests | test projects and what they cover |
| Impact | files each change touches |
| **Conversion** | the prepared conversion: status, worktree and branch, the runbook, the opening message for GitHub Copilot (with a copy button), what the package step changed, and **Verify** |

On disk, under `RUNS_DIR\<engagement>\<repository>\`:

| Folder or file | Contents |
|---|---|
| `0001-<id>\`, ... | each discovery step's output for one run |
| `conversions\<n>\wt\` | the conversion's worktree, on branch `conversion/<n>`: open this folder in Visual Studio to run the conversion |
| `conversions\<n>\RUNBOOK.md` | how to run the conversion, step by step |
| `conversions\<n>\conversion.json` | the conversion's record |
| `conversions\last-prepare.json` | what the last preparation did, or why it skipped its package step |
| `verification\conversion-<n>\VERIFICATION.md` | the verdict and its reasons, after **Verify** |

Run the conversion as `RUNBOOK.md` says, commit on the branch, then press **Verify** in the Conversion section.
A rescan (**Rescan** on the repository's page) refreshes a conversion that has not been run yet; once one has
been run, **Start the next conversion** starts another.

---

## L. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| A feed answers **401** (preflight "HTTP 401", bootstrap stage 6, or a package marked "unknown ... 401 (Unauthorized)" in Dependencies) | The feed needs a login and none was supplied | Add the feed with its login to the account's NuGet configuration: `dotnet nuget add source <address> -n <name> -u <user> -p <token>`; for a feed a scanned repository names, `dotnet nuget update source <name> -u <user> -p <token>`, or install the client's credential provider and sign in once. Leave `NUGET_SOURCES` empty when the login is in the NuGet configuration |
| A feed answers **403** | The login is known but has no right to that feed | Ask the feed's owner for read access for that account; the address and the login are right |
| Stage 3: "No matching distribution found" or "Could not find a version that satisfies the requirement" | The mirror has no wheel of that package for this Python (bootstrap never compiles) | Use a Python 3.11 to 3.14 that the mirror has wheels for (3.13 is the safest), or ask for the mirror to include wheels for `cp314-win_amd64`. Never install a compiler for this |
| git: **"Filename too long"** | The path is over 259 characters and `core.longpaths` is off | `git config --global core.longpaths true` (section C), use shorter folders (section A), then clone again |
| A discovery step fails at once: **"You must install .NET to run this application"** | .NET is installed per user and `DOTNET_ROOT` is not set for the account the backend runs as | Set `DOTNET_ROOT` (section C), open a new window, restart the backend |
| The backend: **"[Errno 10048] ... only one usage of each socket address"**; the frontend: **"Port 5174 is already in use"** | Something already listens on that port, often an earlier window still running | Find it: `Get-NetTCPConnection -LocalPort 8001 -State Listen | Select-Object OwningProcess`, then `Get-Process -Id <id>`. Close that window. To use another port instead, change `API_PORT` (and rerun bootstrap with `-Stage 5` after deleting `frontend\.env`) or the frontend's `--port` and `CORS_ORIGINS` together |
| Conversion section: **"package step skipped: the baseline did not pass: ..."** | The repository does not build, or its tests fail, before any change | Nothing is lost: the conversion is prepared, and its package changes go to the agent as instructions in the runbook. Fix the build in the client repository if it should pass, then **Rescan** |
| **"package step skipped: no package step: test-coverage-assessment found no unit test project"** | The repository has no unit tests, so package upgrades cannot be checked by running them | As above: the package changes are left to the agent, with instructions |
| A step fails with "executable not found" | The step programs are not published | `bootstrap.ps1 -Stage 6 -Force` |
| The UI loads, but every request fails | `frontend\.env` points at another port, or the frontend is not on 5174 (`CORS_ORIGINS`) | Start the frontend exactly as in section I |
| A job shows **"orphaned by engine restart"** | The backend was stopped while it ran | Rescan the repository (or Verify again) |

---

## M. Stopping, restarting, and installing a later release

### Stopping

Press **Ctrl+C** in the backend's window and in the frontend's. Wait until no discovery or verification is
running first (the **Executions** tab): one that is running when the backend stops is marked "orphaned by engine
restart" the next time it starts, and must be started again.

### Restarting

Run the two commands of section I again. Nothing else is needed: the database and `RUNS_DIR` keep everything.

### Installing a later release

A later release arrives as a git bundle, `rbc-release-<n>.bundle`, with a `.sha256` file beside it.

1. Stop the backend and the frontend.
2. Check the bundle arrived intact. The two values must be identical:

   ```powershell
   (Get-FileHash -Algorithm SHA256 .\rbc-release-2.bundle).Hash.ToLower()
   ```

   ```powershell
   Get-Content .\rbc-release-2.bundle.sha256
   ```

3. Bring the release into the platform folder and switch to it. Your `backend\.env`, `frontend\.env`, `.venv`,
   `node_modules` and published programs are not part of git, so they stay:

   ```powershell
   git -C C:\MP\code fetch C:\path\to\rbc-release-2.bundle "refs/tags/rbc-release-2:refs/tags/rbc-release-2"
   ```

   ```powershell
   git -C C:\MP\code checkout rbc-release-2
   ```

4. Run bootstrap again (section H). It updates only what the release changed: new packages, programs whose
   sources changed, new migrations, new configuration.
5. Start the backend and the frontend (section I).

If the platform folder was installed without `.git`, copy the new release to a new folder instead, copy
`backend\.env` into it, run bootstrap there, and start the platform from the new folder.
