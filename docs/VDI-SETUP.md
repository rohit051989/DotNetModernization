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
| [K. Registering a client repository](#k-registering-a-client-repository) | by git URL; signing in to the git host once; what discovery produces |
| [L. Troubleshooting](#l-troubleshooting) | |
| [M. Stopping, restarting, a later release](#m-stopping-restarting-and-installing-a-later-release) | upgrading in place from a release bundle, keeping all data |
| [N. More than one person](#n-more-than-one-person) | one platform per schema, a stale heartbeat, one checkout per engagement |
| [O. Deleting a repository or an engagement](#o-deleting-a-repository-or-an-engagement) | hard delete, the audit |

---

## A. Before starting

### Required versions

Install these first. None needs administrator rights if installed per user (section C shows how for Python and
.NET). Preflight (section G) checks every one and says exactly what is wrong.

| Tool | Version needed | Notes |
|---|---|---|
| **Python** | **3.11 to 3.14, a final release** (tested: 3.14.8) | Never an alpha, beta or release candidate (such as `3.14.0b2`): preflight refuses one. Bootstrap installs the exact package versions the full suite passed with (`backend\requirements.lock`), all from prebuilt wheels, so no compiler is needed. Preflight warns when the Python is older than the tested 3.14.8. 3.15 is refused |
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
- **Read access to the client's git server**, for your own account, to clone the repositories you will scan
  (section K signs in to it once), and the NuGet feeds those repositories use.

### Why paths must be short

Windows tools fail on file paths longer than 260 characters, and git refuses to write a path longer than 259
characters unless `core.longpaths` is on. The platform's own longest file is 159 characters, so its folder must
be shorter than 99 characters. Each conversion is a full copy of a client repository placed several folders deep
under the run folder, beneath the repository's own deepest path. Keep both short:

| Use | Example | Avoid |
|---|---|---|
| Platform folder | `C:\MP\code` | `C:\Users\firstname.lastname\Documents\Projects\Client\Modernization Platform\code` |
| Run folder (`RUNS_DIR`) | `C:\MP\runs` | anything inside the platform folder (refused) |
| Client repositories (`REPOS_DIR`) | `C:\MP\repos`, so a clone lands in `C:\MP\repos\client-a\OrderService` | a deep project-share path; anything inside the platform folder or `RUNS_DIR` (refused) |

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

Then name it in `backend\.env` as `PYTHON=C:\MP\tools\python314\python.exe` (section F): bootstrap and preflight
use it. Left empty, they use `python` on `PATH`.

### .NET installed per user

If the client provides the .NET SDK machine-wide (in `C:\Program Files\dotnet`), skip this, and leave
`DOTNET_ROOT` empty in `backend\.env`. Otherwise install it with Microsoft's script into its own folder, for
example 10.0.203:

```powershell
powershell -ExecutionPolicy Bypass -File .\dotnet-install.ps1 -Version 10.0.203 -InstallDir C:\MP\tools\dotnet -NoPath
```

Then name that folder in `backend\.env` as `DOTNET_ROOT=C:\MP\tools\dotnet` (section F). That is all the platform
needs. The backend, bootstrap and preflight put that folder first on `PATH` and set `DOTNET_ROOT` for every
process they start: the step programs (which find a per-user .NET **only** through `DOTNET_ROOT`, and otherwise
fail at once with "You must install .NET to run this application"), and the package step's and the verifier's
builds and tests. Each build log then starts with the SDK it used, for example
`# .NET SDK 10.0.203, C:\MP\tools\dotnet\dotnet.exe`.

To use that `dotnet` in your own terminals as well (not needed for the platform), add it for your account:

```powershell
[Environment]::SetEnvironmentVariable('Path', 'C:\MP\tools\dotnet;' + [Environment]::GetEnvironmentVariable('Path', 'User'), 'User')
```

---

## D. Package sources

Bootstrap installs the platform's own dependencies: Python packages with pip, the frontend's with npm, and the
NuGet packages the step programs are built from. First work out which case this machine is in.

### Case 1: the machine reaches the public registries

If this machine reaches pypi.org, registry.npmjs.org and api.nuget.org, **you configure nothing**:
- leave `PIP_INDEX_URL`, `NPM_REGISTRY` and `NUGET_SOURCES` empty in `backend\.env`;
- set no pip, npm or NuGet configuration.

That holds whether the connection is direct or through a proxy the client's IT already set for the account (as
`HTTPS_PROXY`, or the Windows system proxy). To find out, run preflight (section G): it tests each source with
pip, npm and dotnet themselves, and prints the proxy it sees. If all three are PRESENT, skip to section E.

### Case 2: a private mirror, usually with a login

If the public registries are blocked, the client has its own mirror (Artifactory, Nexus). Only then do you need
the rest of this section: find the mirror's addresses, and give the tools the login if it asks for one.

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

Put the address in `backend\.env` (below) and run preflight (section G). It tests each source with the tool that
will use it, the way bootstrap uses it:
- **pip** downloads one wheel;
- **npm** asks for one package;
- **dotnet** restores one package into an empty folder.

Proxies, certificates and logins therefore behave exactly as in the real install. A failure shows the tool's own
message:
- "401 (Unauthorized)" means it needs a login (below);
- "No such host is known", "Failed to resolve" or a timeout means this machine cannot reach it, so ask for another
  address.

A quick check from PowerShell (`Invoke-WebRequest <address>`) is not the same test. It does not use pip's, npm's or
NuGet's own proxy, certificate or login settings. On a client VDI it has been reset by the network ("An existing
connection was forcibly closed", WinError 10054) for an address pip installed from without trouble.

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
| `REPOS_DIR` | Optional. Where repositories registered by their git URL are cloned: `<REPOS_DIR>\<engagement>\<repository>`. Absolute, short, outside the platform folder and outside `RUNS_DIR`. Empty: the registration form asks for the folder each time (section K) | `C:\MP\repos` | no |
| `API_HOST` | The address the backend listens on | `127.0.0.1` | no |
| `API_PORT` | Its port. Bootstrap writes the frontend's link to the backend from this | `8001` | no |
| `CORS_ORIGINS` | The frontend's address(es), comma-separated | `http://localhost:5174,http://127.0.0.1:5174` | no |
| `DEPLOYMENT` | `client`. **Never set it to `demo` on the VDI**: `demo` lets the demo-reset script delete every engagement and repository, and this database is the only copy of the client's data | `client` | no |
| `PIP_INDEX_URL` | Section D; empty to use pip's own configuration | `https://artifactory.client.com/artifactory/api/pypi/pypi-remote/simple` | no (put a login in pip's own configuration, not here) |
| `NPM_REGISTRY` | Section D; empty to use npm's own configuration | `https://artifactory.client.com/artifactory/api/npm/npm-remote/` | no |
| `NUGET_SOURCES` | Section D; feed addresses or folders for building the step programs, comma-separated; empty to use the account's NuGet configuration | `https://artifactory.client.com/artifactory/api/nuget/v3/nuget-remote/index.json` | no |
| `COMPARE_PUBLIC_NUGET_FEED` | Whether dependency assessment also asks nuget.org which versions exist publicly. `false` where nuget.org is unreachable | `false` | no |
| `PYTHON` | The Python bootstrap and preflight use, as a full path. Empty: `python` on `PATH`. (The backend itself always runs in `backend\.venv`, which bootstrap builds with this Python) | `C:\MP\tools\python314\python.exe` | no |
| `DOTNET_ROOT` | **Only when .NET is installed per user** (section C): the folder it was installed into. The platform puts it first on `PATH` and sets `DOTNET_ROOT` for every process it starts. **Leave it empty** when the client installed .NET machine-wide | `C:\MP\tools\dotnet` | no |

Every key added by a later release is optional and has a default, so an upgrade never requires editing this file
(section M).

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
REPOS_DIR=C:\MP\repos
API_HOST=127.0.0.1
API_PORT=8001
CORS_ORIGINS=http://localhost:5174,http://127.0.0.1:5174
DEPLOYMENT=client
PIP_INDEX_URL=
NPM_REGISTRY=
NUGET_SOURCES=
COMPARE_PUBLIC_NUGET_FEED=false
PYTHON=C:\MP\tools\python314\python.exe
DOTNET_ROOT=
```

(`DOTNET_ROOT` stays empty here because this client provides .NET machine-wide; with a per-user .NET it would be
`DOTNET_ROOT=C:\MP\tools\dotnet`.)

---

## G. Preflight

Preflight checks everything this guide has set up and changes nothing. Run it with any Python: it checks the one
`PYTHON` names in `backend\.env` (else `python` on `PATH`), and the .NET that `DOTNET_ROOT` names (else `dotnet` on
`PATH`):

```powershell
cd C:\MP\code; C:\MP\tools\python314\python.exe scripts\preflight.py
```


### Reading it

Each line is `PRESENT` or `MISSING`, with what was found and what is needed. The last line counts them:

```
Tools
  PRESENT  Python: 3.14.8 (C:\MP\tools\python314\python.exe, PYTHON in backend\.env; 3.11.0 to 3.14.x needed)
  PRESENT  .NET SDK: 10.0.203 used, from C:\MP\tools\dotnet; installed: 10.0.203 (any .NET 10 SDK from 10.0.100 needed, ...)
  MISSING  .NET runtime for the step programs: dotnet comes from C:\MP\tools\dotnet, but DOTNET_ROOT is not set ...
...
9 present, 1 missing: .NET runtime for the step programs
```

Besides `PRESENT` and `MISSING`:
- `WARNING` lines are worth knowing, but never fail. For example, a Python older than the one the release was tested
  on, 3.14.8.
- The **Proxy** lines show `HTTPS_PROXY`, `HTTP_PROXY` and `NO_PROXY`, any proxy set in pip's or npm's own
  configuration, and the Windows system proxy.
- Each **package source** line says where its address came from (`backend\.env`, or the tool's own
  configuration), whether it goes **through the proxy** or **direct**, and what the tool did. For example,
  "pip ... downloaded the pyyaml==6.0.3 wheel", or the tool's own error.
- The "Long paths" lines are `ON` or `OFF`, and never fail. `NOTE` lines are information only.
- Once the schema exists, the **platform** line says whether a platform holds it: `WARNING ... a platform holds this
  schema` while one runs (yours too: stop it before an upgrade), or a `NOTE` that the last one stopped without
  shutting down and its heartbeat has expired. Section N, "A stale heartbeat".
- **existing data** lines report data an older release allowed and a newer rule would refuse, such as one checkout
  registered in two engagements. They are left working and never changed (section M).

Before bootstrap, the database section reports the database driver as missing: that is expected, bootstrap
installs it.

### Fixing each MISSING item

| MISSING | Fix |
|---|---|
| Python ... too old / too new, or not found | Install a Python 3.11 to 3.14 (section C), and name it as `PYTHON` in `backend\.env` |
| Python ... is a pre-release (alpha, beta, release candidate) | Install the final release: section L, "Replacing a pre-release Python" |
| Node.js ... too old | Install Node.js 22.12 or later (or 20.19+) |
| npm ... too old | Comes with Node.js: update Node.js |
| .NET SDK: none of ... | Install a .NET 10 SDK (section C). A .NET 9 or a preview SDK does not count |
| .NET runtime for the step programs ... DOTNET_ROOT is not set | .NET is installed per user: set `DOTNET_ROOT` in `backend\.env` to the folder it names (sections C and F) |
| git ... too old / not found | Install git 2.17 or later, and open a new window |
| PIP_INDEX_URL / NPM_REGISTRY / NUGET_SOURCES ... failed: "Failed to resolve", "No such host is known", a timeout, "connection broken" | This machine cannot reach that address, or not through the proxy shown on that line. Find one it can (section D), or ask IT which proxy applies |
| ... failed: "401", "Unauthorized" | The source needs a login: give it to the tool's own configuration (section D, "Where each one goes") |
| ... failed: "403", "Forbidden" | The login has no right to that source: ask its owner for read access |
| ... failed: "certificate verify failed", "unable to get local issuer certificate", "SSL" | A proxy or mirror re-signs connections with the client's own certificate, which the tool does not trust yet. Ask IT for the client's standard pip, npm and NuGet certificate settings; do not turn verification off |
| ... failed: "404", "Not Found", "could not find a version" | The address is wrong, often a missing `/simple` for pip or `/index.json` for NuGet, or the mirror lacks the package |
| If preflight's own run is blocked even though the tools work | Section L, "When preflight's own check is blocked" |
| RUNS_DIR: not set / inside the repository / not writable | Set an absolute folder outside `C:\MP\code` that you can write to (section F) |
| REPOS_DIR: not an absolute path / inside the platform's folder / inside RUNS_DIR / not writable | Set it to a short folder of its own, such as `C:\MP\repos`, or leave it empty (section F) |
| connection: ... | Check `DB_HOST`, `DB_PORT`, `DB_NAME`; a "password authentication failed" means `DB_USER` / `DB_PASSWORD`; a timeout means the VDI cannot reach the server (a firewall) |
| connection: ... (17 needed) | The server is not PostgreSQL 17: ask the administrator |
| schema ...: this login cannot create a schema | The login lacks `CREATE` on the database (section E) |
| schema ...: exists, but this login cannot create tables in it | Ask the administrator to make the login the schema's owner |
| scratch schemas | The login lacks `CREATE` on the database (section E) |

---

## H. Bootstrap

Bootstrap installs and sets up everything, in eight stages. It uses the Python `PYTHON` names in `backend\.env`
(else `python` on `PATH`) and the .NET `DOTNET_ROOT` names (else `dotnet` on `PATH`):

```powershell
cd C:\MP\code; powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

It prints the Python and, when set, the `DOTNET_ROOT` it uses. `-Python <full path>` overrides `PYTHON` for one
run.

**It is safe to run again at any time.** Each stage skips work already done: a second run takes seconds. To run
one stage only, add `-Stage <n>`; to make a stage redo its work even when it looks up to date, add `-Force`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -Stage 6 -Force
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

## K. Registering a client repository

The main way: give the platform the repository's git URL. Its discovery job clones the repository, then scans it,
and a later **Rescan** fetches the newest commits first. A repository you already cloned yourself can still be
registered by its folder (the end of this section).

### Signing in to the client's git host, once

The platform runs git as you, with your own credentials: Git Credential Manager (installed with Git for Windows)
for an https URL, your SSH key for an SSH one. It never asks for, stores or logs a credential. It cannot answer a
sign-in prompt either, so a clone that needs a sign-in fails at once and says so. Sign in once, outside the
platform, in your own PowerShell window:

```powershell
git ls-remote https://git.client.com/team/OrderService.git
```

- **https:** Git Credential Manager opens its sign-in window (the client's single sign-on, or a personal access
  token if the git host asks for one). It remembers the sign-in for your account, so every later clone and fetch,
  including the platform's, uses it. The command then lists the repository's branches.
- **SSH** (`git@git.client.com:team/OrderService.git`): the first time, answer `yes` to the host's key. A key with a
  passphrase must be loaded into the ssh-agent (`ssh-add`), because the platform cannot type a passphrase.

When a clone fails with "needs a sign-in the platform cannot give", do this, then press **Rescan** on the
repository's page (or register again).

### Register it

In the UI, choose the engagement in **View**, then **Repositories** → **+ Register Repository**. **Git URL** is
selected:

1. **Git URL:** `https://git.client.com/team/OrderService.git` (or `git@...`, `ssh://...`; a URL must not contain a
   user name or password, and one that does is refused). A repository in a folder or on a share can be given as
   `file:///C:/mirror/OrderService.git`.
2. **Branch** (optional): the branch to clone and follow. Empty: the repository's default branch.
3. **Target folder** (optional when `REPOS_DIR` is set): where to clone it. Empty: `<REPOS_DIR>\<engagement>\<repository>`,
   for example `C:\MP\repos\client-a\OrderService`. The form says what will happen when you leave the field: a new or
   empty folder is cloned into; **an existing clone of the same URL is used as it is**; any other folder that is not
   empty is refused, as is a folder inside the platform's or `RUNS_DIR`.
4. **Register, clone & launch discovery.**

From the command line (the backend need not be running):

```powershell
cd C:\MP\code\backend; .venv\Scripts\python.exe -m app.repositories.cli register-url --engagement client-a --url https://git.client.com/team/OrderService.git
```

`--branch` and `--target C:\MP\repos\client-a\OrderService` are optional, as in the form.

**While it clones**, the repository's row and page show `cloning` and git's progress ("Receiving objects: 45%").
The clone is full (every branch and its history, not shallow) with `core.longpaths=true`. A failure shows git's own
message and what to do, for example how to sign in. Discovery and preparation then follow, exactly as for a
folder.

If the repository's `nuget.config` names a feed by a relative folder (for example `..\EnterprisePackages\feed`),
place that folder beside the clone, exactly where the path points.

### Rescan of a cloned repository

**Rescan** on the repository's page first fetches from its URL and fast-forwards its branch, then scans the commit
it reaches. A conversion that has not been run yet moves onto that commit; once one has been run, **Start the next
conversion** prepares a new one from it (below). The fetch refuses, changing nothing, when:
- the clone has local changes (edited files, even uncommitted ones): commit, stash or discard them outside the
  platform;
- the clone is on another branch than the one registered: switch it back;
- the branch has commits the remote does not have: resolve that outside the platform.

The conversions themselves live in worktrees under `RUNS_DIR`, on their own branches, so they never count as local
changes of the clone.

### Registering a folder you cloned yourself

Choose **Local folder path** in the form instead:

```powershell
git clone -c core.longpaths=true https://git.client.com/team/OrderService.git C:\MP\repos\OrderService
```

1. **Local folder path:** `C:\MP\repos\OrderService`, then leave the field. The form inspects the folder and fills
   in the clone URL from its `origin` remote. A repository with no remote at all registers without one.
2. **Register & launch discovery.**

A folder registered this way is never fetched by the platform: pull new commits into it yourself before **Rescan**.
If git reports "dubious ownership" for a repository you copied rather than cloned, see section B.

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
| Dependencies | every package: the version in use, the recommended version, its outcome and flags, and a **Reason** in plain words for each (the advisory, its severity and the version that fixes it; why an upgrade is safe; which shared framework provides it; the publisher's named successor; why a lookup did not answer, such as a feed returning 401). "Vulnerable" always refers to the version in use |
| Surface (SOAP compatibility) | each SOAP call per environment: the Runtime and Platform verdicts, a **Why** beside each (the matrix entry that decided it and its probe evidence, or why it is unknown), and whether a named person has **confirmed** that entry (reviewed its evidence and accepted it) |
| Work list | the catalog items found, where, and how each is to be resolved |
| Tests | test projects and what they cover |
| Impact | files each change touches |
| **Conversion** | every conversion, newest first: number, branch, status (prepared, run, verified) and verdict. Each one's entry has the commit it starts from, its worktree, the runbook, the opening message for GitHub Copilot (with a copy button), its package-step plan, **Verify** once it has been run, and its VERIFICATION.md once verified |

On disk, under `RUNS_DIR\<engagement>\<repository>\`:

| Folder or file | Contents |
|---|---|
| `0001-<id>\`, ... | each discovery step's output for one run |
| `conversions\<n>\wt\` | the conversion's worktree, on branch `conversion/<n>`: open this folder in Visual Studio to run the conversion |
| `conversions\<n>\RUNBOOK.md` | how to run the conversion, step by step |
| `conversions\<n>\conversion.json` | the conversion's record |
| `conversions\last-prepare.json` | what the last preparation did, or why it skipped its package step |
| `verification\conversion-<n>\VERIFICATION.md` | the verdict and its reasons, after **Verify** |

Run the conversion as `RUNBOOK.md` says, commit on the branch, then press **Verify** in its entry in the
Conversion section.

A conversion always starts from the commit discovery scanned. When the client repository gets new commits:
- a repository registered by URL: **Rescan** fetches them; a folder registered by path: pull them into it first;
- **Rescan** (on the repository's page) moves a conversion that has not been run yet onto the new commit;
- once a conversion has been run, **Start the next conversion** prepares a new one, on a new branch, from the
  new commit. It asks first, naming the branch and the commit; it changes no existing conversion and runs no
  engine.

---

## L. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| A feed answers **401** (preflight "HTTP 401", bootstrap stage 6, or a package marked "unknown ... 401 (Unauthorized)" in Dependencies) | The feed needs a login and none was supplied | Add the feed with its login to the account's NuGet configuration: `dotnet nuget add source <address> -n <name> -u <user> -p <token>`; for a feed a scanned repository names, `dotnet nuget update source <name> -u <user> -p <token>`, or install the client's credential provider and sign in once. Leave `NUGET_SOURCES` empty when the login is in the NuGet configuration |
| A feed answers **403** | The login is known but has no right to that feed | Ask the feed's owner for read access for that account; the address and the login are right |
| Stage 3: "No matching distribution found" or "Could not find a version that satisfies the requirement" | The mirror has no wheel of that package for this Python (bootstrap never compiles) | Use a Python 3.11 to 3.14 that the mirror has wheels for (3.13 is the safest), or ask for the mirror to include wheels for `cp314-win_amd64`. Never install a compiler for this |
| git: **"Filename too long"** | The path is over 259 characters and `core.longpaths` is off | `git config --global core.longpaths true` (section C), use shorter folders (section A), then clone again |
| A discovery step fails at once: **"You must install .NET to run this application"** | .NET is installed per user and `DOTNET_ROOT` is not set in `backend\.env` | Set `DOTNET_ROOT` (sections C and F), restart the backend |
| The backend: **"[Errno 10048] ... only one usage of each socket address"**; the frontend: **"Port 5174 is already in use"** | Something already listens on that port, often an earlier window still running | Find it: `Get-NetTCPConnection -LocalPort 8001 -State Listen | Select-Object OwningProcess`, then `Get-Process -Id <id>`. Close that window. To use another port instead, change `API_PORT` (and rerun bootstrap with `-Stage 5` after deleting `frontend\.env`) or the frontend's `--port` and `CORS_ORIGINS` together |
| Conversion section: **"package step skipped: the baseline did not pass: ..."** | The repository does not build, or its tests fail, before any change | Nothing is lost: the conversion is prepared, and its package changes go to the agent as instructions in the runbook. Fix the build in the client repository if it should pass, then **Rescan** |
| **"package step skipped: no package step: test-coverage-assessment found no unit test project"** | The repository has no unit tests, so package upgrades cannot be checked by running them | As above: the package changes are left to the agent, with instructions |
| A step fails with "executable not found" | The step programs are not published | `bootstrap.ps1 -Stage 6 -Force` |
| The UI loads, but every request fails | `frontend\.env` points at another port, or the frontend is not on 5174 (`CORS_ORIGINS`) | Start the frontend exactly as in section I |
| A job shows **"orphaned by engine restart"** | The backend was stopped while it ran | Rescan the repository (or Verify again) |
| Preflight: **"Python: 3.14.0b2 ... is a pre-release"** | Software Center (or a download) gave an alpha, beta or release candidate | Replace it with a final release: "Replacing a pre-release Python", below |
| The backend does not start: **"Another Modernization Platform is already running on ..."** | Someone else's platform (or a second one of yours) uses the same schema, or one that stopped without shutting down less than 90 s ago | Each person needs their own schema: section N. If that platform has stopped (its VDI session closed, its machine restarted), start again after the seconds the message gives, or clear it: section N, "A stale heartbeat" |
| Registering by URL: **"... needs a sign-in the platform cannot give"** | git has no stored sign-in for that host, or no SSH key it can use without a passphrase | Sign in once outside the platform (section K, "Signing in to the client's git host, once"), then **Rescan** |
| Registering by URL: **"... exists and is not empty"** or **"is already a clone of another repository"** | The target folder holds something else | Choose another target folder, or empty it. An existing clone of the same URL is used as it is |
| Rescan of a cloned repository: **"has local changes"**, **"is on ... but this repository is registered on ..."**, **"cannot be fast-forwarded"** | Someone edited the clone, switched its branch, or committed in it | Commit, stash or discard the change, switch back, or resolve the divergence, outside the platform; then **Rescan** (section K). Nothing was changed |
| Delete: **"Some files could not be removed, so nothing was deleted from the database"** | A program holds a file under `RUNS_DIR` open, usually Visual Studio with a conversion's worktree | Close it and delete again; it picks up where it stopped (section O) |
| Registering: **"This checkout is already registered in engagement ..."** | One folder (or a worktree of it) is in another engagement already | Clone the repository again into another folder and register that (section N) |

### Replacing a pre-release Python

A pre-release (`3.14.0b2`, `3.14.0rc1`) is refused by preflight. Packages with compiled parts (pydantic-core,
psycopg) publish wheels for final releases, and an interpreter that is still changing can break them. On one VDI,
pydantic failed in bootstrap stage 7 on 3.14.0b2.

1. Install a final release, for example 3.14.8, per user (section C), or ask Software Center for the final release.
   The pre-release can stay installed: nothing uses it once `PYTHON` names the new one.
2. Name it in `backend\.env`: `PYTHON=C:\MP\tools\python314\python.exe`.
3. Delete `backend\.venv` (it was built with the pre-release), then run preflight and bootstrap again. Bootstrap
   rebuilds the environment with the final release and installs the locked versions into it.

### When preflight's own check is blocked

Preflight runs each check with pip, npm and dotnet themselves, so it sees what bootstrap will see. If preflight
still cannot complete on a machine where the tools themselves work, run bootstrap's stages one at a time, without
stage 1, and stop at the first that fails. Stage 1 is preflight; each later stage does its own work and says
plainly when it fails.

```powershell
cd C:\MP\code; foreach ($s in 2..8) { powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -Stage $s; if ($LASTEXITCODE -ne 0) { Write-Host "Stopped at stage $s"; break } }
```

Stage 4 is preflight's database check. If that is the part that is blocked, leave it out:

```powershell
cd C:\MP\code; foreach ($s in 2, 3, 5, 6, 7, 8) { powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -Stage $s; if ($LASTEXITCODE -ne 0) { Write-Host "Stopped at stage $s"; break } }
```

Stage 7 (the migration) then shows whether the database works.

### The ".NET Host" compliance warning

On a managed VDI, the client's endpoint security or compliance agent may raise a warning naming **.NET Host**
(`dotnet.exe`) when the platform runs it, typically when .NET is installed per user (section C) rather than through
Software Center.

**What it means.** The agent sees an executable it does not manage running from the user's profile. `dotnet.exe` is
Microsoft's own, signed program: the same .NET that Software Center would install. The platform runs it for every
build, test and discovery step, so the warning appears whenever those run.

**What to do.** Do not try to silence or work around the agent. Raise it with the client's IT or security team,
naming the folder (for example `C:\MP\tools\dotnet`) and the version. Ask them either to allow that per-user
installation, or to install a .NET 10 SDK machine-wide through Software Center. In the second case, leave
`DOTNET_ROOT` empty in `backend\.env` and run bootstrap again.

---

## M. Stopping, restarting, and installing a later release

### Stopping

Press **Ctrl+C** in the backend's window and in the frontend's. Wait until no discovery or verification is
running first (the **Executions** tab): one that is running when the backend stops is marked "orphaned by engine
restart" the next time it starts, and must be started again.

### Restarting

Run the two commands of section I again. Nothing else is needed: the database and `RUNS_DIR` keep everything.

### Installing a later release: upgrading in place

**Every release upgrades an existing installation in place and keeps all its data**: the database schema, `RUNS_DIR`,
the clones, `backend\.env` and `frontend\.env`. Its migrations only add to the schema or extend it, never drop or
rewrite what is there, and every new setting is optional with a default, so `backend\.env` needs no edit. Data an
older release allowed and a newer rule would refuse (such as one checkout registered in two engagements before
rbc-release-2) is reported by preflight and in the backend's log, and left working, never changed or deleted. A
release that cannot upgrade in place says so in its release notes, with the reason; none so far.

A release arrives as a git bundle, `rbc-release-<n>.bundle`, with `rbc-release-<n>.bundle.sha256` beside it. The
commands below upgrade `C:\MP\code` to rbc-release-2 from `C:\MP\delivery`; for another release, change the two
names. Run them in one PowerShell window, in order.

1. **Stop the platform.** Wait until no discovery or verification is running (the **Executions** tab), then press
   **Ctrl+C** in the backend's window and in the frontend's.
2. **Back up the schema.** Ask the database administrator for a backup of `DB_SCHEMA` first. The upgrade only adds
   to it, but a backup costs little.
3. **Check the bundle arrived intact.** The two lines must be identical:

   ```powershell
   (Get-FileHash -Algorithm SHA256 C:\MP\delivery\rbc-release-2.bundle).Hash.ToLower()
   ```

   ```powershell
   (Get-Content C:\MP\delivery\rbc-release-2.bundle.sha256).Split(' ')[0]
   ```

4. **Check the platform folder has nothing of yours in it.** git must print nothing (your `.env` files, `.venv`,
   `node_modules` and published programs are ignored by git and stay):

   ```powershell
   git -C C:\MP\code status --porcelain --untracked-files=no
   ```

   If it lists files, they were edited by hand: copy them aside, then `git -C C:\MP\code checkout -- .`.
5. **Bring the release in and switch to it:**

   ```powershell
   git -C C:\MP\code fetch C:\MP\delivery\rbc-release-2.bundle "refs/tags/rbc-release-2:refs/tags/rbc-release-2"
   ```

   ```powershell
   git -C C:\MP\code -c core.longpaths=true checkout rbc-release-2
   ```

   ```powershell
   git -C C:\MP\code log -1 --format="%h %d"
   ```

   The last command shows the release's commit and `tag: rbc-release-2`. git says it is in "detached HEAD" state:
   that is expected for a release.
6. **Preflight:**

   ```powershell
   cd C:\MP\code; C:\MP\tools\python314\python.exe scripts\preflight.py
   ```

   (your `PYTHON`, as in section G). Fix anything `MISSING` (section G). Read any `WARNING ... existing data` line:
   it is reported, not a failure.
7. **Bootstrap:**

   ```powershell
   cd C:\MP\code; powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
   ```

   It updates only what the release changed and skips the rest. It ends with `Bootstrap complete`.
8. **Start the platform** (section I). Your engagements, repositories, conversions and verifications are all there.

**What rbc-release-3 changes on an rbc-release-2 installation** (upgrade with the commands above, with
`rbc-release-3` in place of `rbc-release-2`). Nothing in the database changes, and no setting is added:
- **stage 6** republishes the step programs: `outbound-invocation-inventory` now reads WCF client platform matrix
  1.2.0;
- the UI: a **Reason** column in Dependencies, a **Why** beside each SOAP verdict (also in the CSV export, as
  `runtime_why` and `platform_why`), and what **Confirmed** means wherever it is shown;
- platform matrix 1.2.0 adds specific Linux entries for basicHttpsBinding Transport/None and Transport/Certificate,
  unconfirmed. Repositories scanned before the upgrade keep their verdicts until they are rescanned: the SOAP
  report then says the run used an older matrix than the newest. **Rescan** each repository with SOAP calls.

**What rbc-release-2 changes on an rbc-release-1 installation:**
- **stage 3** installs the exact versions in `backend\requirements.lock`; packages may move to the locked versions;
- **stage 6** republishes the step programs whose sources changed;
- **stage 7** adds the tables `platform_heartbeat` (section N) and `deletion_audit` (section O), and lets a
  repository's status be `cloning` with a `clone_progress` column (section K). Nothing existing changes;
- **stage 8** reseeds, which never overwrites a catalog edit made in the UI;
- new, optional setting `REPOS_DIR` (section F): without it, registering by URL asks for the target folder;
- new in the UI: **Git URL** registration (section K), **Delete engagement…** and a hard **Delete** on a
  repository's page (section O); a checkout already registered in two engagements is reported (section N).

If the platform folder was installed without `.git` (step 5 fails with "not a git repository"), clone the release
into a new folder instead, copy `backend\.env` and `frontend\.env` into it, run steps 6 to 8 there, and start the
platform from the new folder. It uses the same schema and `RUNS_DIR`, so the data is the same:

```powershell
git clone -c core.longpaths=true --branch rbc-release-2 C:\MP\delivery\rbc-release-2.bundle C:\MP\code2
```

---

## N. More than one person

The platform runs for one person, on one machine (`CLAUDE.md`, "Operating model"). It runs its jobs inside its own
process, and when it starts it fails every job still marked as running, assuming a previous process of its own
stopped. Two platforms on one schema would fail each other's running jobs, then run each other's work. So:

- **One platform per schema.** A running platform keeps a heartbeat in its schema. A second platform started on the
  same schema, whether someone else's or a second one of yours, refuses to start before it touches anything. It says
  who holds the schema, from which machine and folder, and when it was last seen.
- **One checkout per engagement.** The platform creates its conversion branches (`conversion/1`, ...) and their
  worktrees in the registered checkout's git. So a checkout, or a worktree of it, is registered in one engagement
  only. Registering it in a second is refused, with the engagement that has it. To use the same repository in a
  second engagement, clone it again into another folder and register that.

### A stale heartbeat

A running platform renews its heartbeat every 20 seconds, and **a heartbeat expires 90 seconds after it was last
renewed**. So a platform that stopped without shutting down (its VDI session closed, its process killed, its
machine restarted) blocks the next start for at most 90 seconds. On the same machine there is no wait at all: a
heartbeat whose process no longer exists is taken over at once. The age is measured on the database server's clock,
so machines whose clocks disagree cannot keep a heartbeat alive.

When the platform refuses to start, its message says who holds the schema and how many seconds are left. Wait that
long and start again, or, when you know that platform has stopped, clear its heartbeat:

```powershell
cd C:\MP\code\backend; .venv\Scripts\python.exe -m app.heartbeat show
```

```powershell
cd C:\MP\code\backend; .venv\Scripts\python.exe -m app.heartbeat clear
```

`show` says who holds it and whether it is live or expired. `clear` asks you to type `clear` while the heartbeat
is still live, and refuses outright when its process is still running on this machine. Preflight reports the
heartbeat too (section G).

### A second person on the same VDI or database

Each person sets up their own platform; nothing is shared but the database server:

1. **Their own copy of the code**, in their own short folder, for example `C:\MP2\code` (section B).
2. **Their own schema**, in the same database. Ask the database administrator for a second login with the same
   rights (section E), or use the same login with a second schema name. The schema name follows the rules in
   section E, for example `modplatform_asmith`. The platform creates the schema on first use.
3. **Their own `backend\.env`**, copied from the first person's and changed:

   | Key | First person | Second person |
   |---|---|---|
   | `DB_SCHEMA` | `modplatform` | `modplatform_asmith` |
   | `DB_USER`, `DB_PASSWORD` | theirs | theirs, if they have their own login |
   | `RUNS_DIR` | `C:\MP\runs` | `C:\MP2\runs` (never shared: it holds each person's worktrees and conversions) |
   | `API_PORT` | `8001` | `8002`, if both run on the same machine at once |
   | `CORS_ORIGINS` | `http://localhost:5174,...` | `http://localhost:5175,http://127.0.0.1:5175` |

4. **Their own clones of the client repositories** (section K): never the first person's folders.
5. Preflight and bootstrap as in sections G and H. Then start their frontend on their port:
   `npm run dev -- --port 5175 --strictPort`.

Each platform then sees only its own engagements; the catalog is seeded into each schema.

---

## O. Deleting a repository or an engagement

**Delete** on a repository's page removes the repository from its engagement. **Delete engagement…** on the
Repositories page removes the engagement and every repository in it. Both are hard deletes and cannot be undone. The
same, from the command line:

```powershell
cd C:\MP\code\backend; .venv\Scripts\python.exe -m app.deletion.cli repository --engagement client-a --repository orderservice
```

```powershell
cd C:\MP\code\backend; .venv\Scripts\python.exe -m app.deletion.cli engagement --engagement client-a
```

Add `--dry-run` to see what would go without deleting anything.

**What goes:**
- every database row of it;
- its folders under `RUNS_DIR`;
- in each registered checkout, the worktrees the platform made and the branches the platform created (the ones
  its records name: `conversion/<n>`, experiment branches).

**What stays:**
- **the repository itself, however it was registered.** A clone the platform made from a git URL stays exactly where
  it is, like a folder registered by its path. Registering the same URL again later reuses that clone (section K);
- any branch the platform did not create, and any branch another registration of the same checkout also records
  (section N);
- the folders beside a checkout that a conversion's worktree linked to (`EnterprisePackages`);
- the catalog, the package lookup cache, and every other repository and engagement.

After a repository is deleted, the engagement's estate view still counts it until the estate is consolidated
again.

**Before anything goes**, the dialog (or the command) says plainly that the repository's folder stays, and shows
exactly what will go. That includes every conversion
that has been run: the agent's work lives only on its branch and goes with it, so push or copy anything you want to
keep first. You confirm by typing the repository's or engagement's name. A delete is refused while a job of it is
running.

If a program holds a file open (Visual Studio with a worktree, a terminal inside a folder), nothing is deleted from
the database. Close it and delete again: it carries on from where it stopped.

**Every delete is recorded** (what, by whom, from where, when), apart from the data it removed:

```powershell
cd C:\MP\code\backend; .venv\Scripts\python.exe -m app.deletion.cli audit
```

A repository can be registered again after its delete. Discovery and preparation start afresh, with no leftovers
in the way.
