# Installing and updating the Modernization Platform on the client VDI

This is the complete guide for the platform on the client's Windows virtual desktop (VDI). It is written for someone
doing it for the first time, with nobody to ask. Every command is PowerShell, run in an ordinary (not administrator)
PowerShell window.

The platform runs on this one machine, for one person (`CLAUDE.md`, "Operating model"): the backend, the frontend,
the step programs, and the repositories it scans all live here; the database is the client's PostgreSQL server.

**Two folders.** The client keeps the platform in a folder inside one of its own git repositories, which other people
also work in, on their own branches, or at the root of a repository dedicated to it ("Two layouts", below). You work
on your own branch. Our `.git` never goes there. So the VDI has:

| Folder | Example | What it is |
|---|---|---|
| **The source folder** | `C:\MP\source` | A clone of our company repository, kept pristine. Only ever copied from |
| **The platform folder** | `C:\MP\client\modernization-platform` | A folder inside the client's repository (`C:\MP\client`), on your own branch. The platform runs here |
| Run output (`RUNS_DIR`) | `C:\MP\runs` | Outside both repositories |
| Cloned client repositories (`REPOS_DIR`) | `C:\MP\repos` | Outside both repositories |

**Two layouts.** The platform folder is one of these, and the scripts work out which from the path they are given:

| Layout | Platform folder | When to use it |
|---|---|---|
| **A folder** in a shared repository | `C:\MP\client\modernization-platform`, inside `C:\MP\client` | The client keeps the platform beside other work, in a repository other people also use. Only the folder is ever checked, committed or delivered; the rest of the repository is untouched |
| **The root** of a dedicated repository | `C:\MP\platform`, the repository itself | The client gives the platform a repository of its own, laid out exactly as ours. The whole repository is the platform |

At the root, our files replace the client's files of the same name (`.gitignore`, `README.md`, `.gitattributes`,
and any other), and each one replaced is listed. A file that was never ours is kept, and listed as "not part of the
platform", exactly as in a folder; `.git` is never copied or touched, and `.env` files are always kept. A new
repository from the client's git host usually holds its own `README.md` and `.gitignore`: the first delivery
replaces them with ours, which is expected. Every check that looks at "only the platform folder" (uncommitted
changes, the delivery commit, client changes not yet imported) looks at the whole repository instead. The examples
in this guide use the folder layout; for the root, use the repository's own path wherever they name the platform
folder, and leave out the folder name in `git add` and `git commit`.

**The rules:**
1. **Never run anything in the source folder.** No bootstrap, no backend, no edits. It is only copied from, and only
   `scripts\update-platform.ps1` pulls it.
2. **Never commit outside the platform folder.** In a shared repository, the rest of it is other people's work. Stage
   and commit only with a path: `git add -A -- modernization-platform`, `git commit -- modernization-platform`. (At
   the root of a dedicated repository the whole repository is the platform folder.)
3. **Only ever commit to your own branch.** Never switch to, commit to, or push anyone else's branch.

| | |
|---|---|
| **Part 1. First-time setup** | |
| ["Before starting"](#before-starting) | versions, access, short paths |
| ["Account settings"](#account-settings) | core.longpaths, Python and .NET per user |
| ["Package sources"](#package-sources) | finding pip, npm and NuGet addresses |
| ["Database"](#database) | schema name, rights |
| ["The source folder and the platform folder"](#the-source-folder-and-the-platform-folder) | cloning ours, your branch, copying in, PLATFORM_SOURCE.json |
| ["backend\.env"](#backendenv) | every key |
| ["Committing the platform folder"](#committing-the-platform-folder-and-pushing-your-branch) | only the platform folder, only your branch |
| ["Preflight"](#preflight) | running it, fixing each MISSING |
| ["Bootstrap"](#bootstrap) | stage by stage |
| ["Starting the backend and the frontend"](#starting-the-backend-and-the-frontend) | commands, ports |
| ["The first admin, and signing in"](#the-first-admin-and-signing-in) | `create-first-admin`, once |
| ["Creating the engagement"](#creating-the-engagement) | UI or command |
| ["Registering a client repository"](#registering-a-client-repository) | by git URL; what discovery produces |
| ["Moving an existing install that carries our .git"](#moving-an-existing-install-that-carries-our-git) | keeping its database, RUNS_DIR, REPOS_DIR and .env |
| **Part 2. Ongoing** | |
| ["Updating the platform"](#updating-the-platform) | stop, update-platform.ps1 (our master), bootstrap, start |
| ["Delivering to a client from our machine"](#delivering-to-a-client-from-our-machine) | when the client's environment cannot reach our git: master's files only, never our history |
| ["Importing a client's changes"](#importing-a-clients-changes) | changes made in the client's copy come back into our repository: the deny-list, branch mapping, merge rule; import first, then deliver |
| ["Users and sign-in"](#users-and-sign-in) | for admins: registering developers, roles, owners, resets; who did what |
| ["More than one person"](#more-than-one-person) | one shared database, one backend per machine, jobs on their machine |
| ["Deleting a repository or an engagement"](#deleting-a-repository-or-an-engagement) | hard delete, the audit |
| ["Troubleshooting"](#troubleshooting) | |
| ["Appendix: upgrading from a bundle of master"](#appendix-upgrading-from-a-bundle-of-master) | our own installs only |
| ["Upgrade notes"](#upgrade-notes) | newest first: what needs doing after an update, besides bootstrap |

Reference material this guide points to, in `01-ENVIRONMENT-SETUP.md` section 10: the full list of network
destinations, how NuGet feeds resolve for scanned repositories, and what stays inside the platform's database
schema.

---

## Part 1. First-time setup

### Before starting


#### Required versions

Install these first. None needs administrator rights if installed per user ("Account settings" shows how for Python and
.NET). Preflight ("Preflight") checks every one and says exactly what is wrong.

| Tool | Version needed | Notes |
|---|---|---|
| **Python** | **3.11 to 3.14, a final release** (tested: 3.14.8) | Never an alpha, beta or release candidate (such as `3.14.0b2`): preflight refuses one. Bootstrap installs the exact package versions the full suite passed with (`backend\requirements.lock`), all from prebuilt wheels, so no compiler is needed. Preflight warns when the Python is older than the tested 3.14.8. 3.15 is refused |
| **Node.js** | **20.19.0 or a later 20.x, or 22.12.0 or later** (tested: 24.13.0) | 21.x is refused. npm comes with it |
| **npm** | **7.0.0 or later** | Every Node.js above ships a newer one |
| **.NET SDK** | **any .NET 10 SDK, 10.0.100 or later** (tested: 10.0.203 and 10.0.302) | Any feature band (1xx, 2xx, 3xx). The .NET 9 SDK alone is not enough |
| **git** | **2.17.0 or later** (tested: 2.55.0) | |
| Visual Studio with GitHub Copilot | the client's standard | Only for running a conversion ("Registering a client repository"); the platform does not need it. When installed (2022 or later, Community, Professional or Enterprise), file links in the UI can open in it, at the line, each installation by its own name (`04-FRONTEND-SPEC.md` "File links"). SQL Server Management Studio and Build Tools are never used, though the Visual Studio Installer lists them |
| VS Code | any | Optional. When `code` is on PATH, file links in the UI can open in it, at the line. Without either editor, file links copy the path and line |

#### Access needed

Ask for these before you start:

- **An account on the VDI.** No administrator rights are needed.
- **A folder you can write to, with a short path**, such as `C:\MP` (the client VDI has only a C drive), for the source folder, the
  client's repository, `RUNS_DIR` and `REPOS_DIR`.
- **Your own branch in the client's shared repository**, with the right to push it, and the folder name the
  client wants the platform in (this guide uses `modernization-platform`).
- **A PostgreSQL 17 database and a login for the platform**, from the client's database administrator. "Database"
  gives them the exact request.
- **Package mirrors the VDI can reach:** one each for Python (pip), npm and NuGet, or direct access to pypi.org,
  registry.npmjs.org and nuget.org. "Package sources" shows how to find what works.
- **Read access to the client's git server**, for your own account, to clone the repositories you will scan
  ("Registering a client repository" signs in to it once), and the NuGet feeds those repositories use.

#### Why paths must be short

Windows tools fail on file paths longer than 260 characters, and git refuses to write a path longer than 259
characters unless `core.longpaths` is on. The platform's own longest file is 159 characters, so its folder must
be shorter than 99 characters. Each conversion is a full copy of a client repository placed several folders deep
under the run folder, beneath the repository's own deepest path. Keep both short:

| Use | Example | Avoid |
|---|---|---|
| Source folder | `C:\MP\source` | anything inside the client's repository |
| Platform folder | `C:\MP\client\modernization-platform` | `C:\Users\firstname.lastname\Documents\Projects\Client\Repo\Modernization Platform` |
| Run folder (`RUNS_DIR`) | `C:\MP\runs` | anything inside the platform folder (refused) or the client's repository |
| Client repositories (`REPOS_DIR`) | `C:\MP\repos`, so a clone lands in `C:\MP\repos\client-a\OrderService` | a deep project-share path; anything inside the platform folder or `RUNS_DIR` (refused) |

"Account settings" turns `core.longpaths` on for your account as well.

### Account settings


All of these are settings for your account only. Open a **new** PowerShell window after changing any of them.

#### git long paths

```powershell
git config --global core.longpaths true
```

#### Python, installed per user

If the client provides Python, skip this. Otherwise, for example Python 3.14 into `C:\MP\tools\python314`:

```powershell
.\python-3.14.8-amd64.exe /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 TargetDir=C:\MP\tools\python314
```

Then name it in `backend\.env` as `PYTHON=C:\MP\tools\python314\python.exe` ("backend\.env"): bootstrap and preflight
use it. Left empty, they use `python` on `PATH`.

#### .NET installed per user

If the client provides the .NET SDK machine-wide (in `C:\Program Files\dotnet`), skip this, and leave
`DOTNET_ROOT` empty in `backend\.env`. Otherwise install it with Microsoft's script into its own folder, for
example 10.0.203:

```powershell
powershell -ExecutionPolicy Bypass -File .\dotnet-install.ps1 -Version 10.0.203 -InstallDir C:\MP\tools\dotnet -NoPath
```

Then name that folder in `backend\.env` as `DOTNET_ROOT=C:\MP\tools\dotnet` ("backend\.env"). That is all the platform
needs. The backend, bootstrap and preflight put that folder first on `PATH` and set `DOTNET_ROOT` for every
process they start: the step programs (which find a per-user .NET **only** through `DOTNET_ROOT`, and otherwise
fail at once with "You must install .NET to run this application"), and the package step's and the verifier's
builds and tests. Each build log then starts with the SDK it used, for example
`# .NET SDK 10.0.203, C:\MP\tools\dotnet\dotnet.exe`.

To use that `dotnet` in your own terminals as well (not needed for the platform), add it for your account:

```powershell
[Environment]::SetEnvironmentVariable('Path', 'C:\MP\tools\dotnet;' + [Environment]::GetEnvironmentVariable('Path', 'User'), 'User')
```

### Package sources


Bootstrap installs the platform's own dependencies: Python packages with pip, the frontend's with npm, and the
NuGet packages the step programs are built from. First work out which case this machine is in.

#### Case 1: the machine reaches the public registries

If this machine reaches pypi.org, registry.npmjs.org and api.nuget.org, **you configure nothing**:
- leave `PIP_INDEX_URL`, `NPM_REGISTRY` and `NUGET_SOURCES` empty in `backend\.env`;
- set no pip, npm or NuGet configuration.

That holds whether the connection is direct or through a proxy the client's IT already set for the account (as
`HTTPS_PROXY`, or the Windows system proxy). To find out, run preflight ("Preflight"): it tests each source with
pip, npm and dotnet themselves, and prints the proxy it sees. If all three are PRESENT, skip to "Database".

#### Case 2: a private mirror, usually with a login

If the public registries are blocked, the client has its own mirror (Artifactory, Nexus). Only then do you need
the rest of this section: find the mirror's addresses, and give the tools the login if it asks for one.

#### What the machine already uses

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

#### From a client repository's nuget.config

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

#### Checking an address works

Put the address in `backend\.env` (below) and run preflight ("Preflight"). It tests each source with the tool that
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

#### Where each one goes

| Tool | Setting in `backend\.env` | If it needs a login |
|---|---|---|
| pip | `PIP_INDEX_URL` (the address ending in `/simple`) | Leave `PIP_INDEX_URL` empty and put the address with its login in your pip configuration: `py -m pip config set global.index-url https://user:token@host/.../simple` |
| npm | `NPM_REGISTRY` | Leave it empty and set the registry and its token with `npm config set registry ...` and `npm login`, or as the client's standard `.npmrc` says |
| NuGet | `NUGET_SOURCES` (comma-separated if several) | Leave it empty and add the feed with its login to your account's NuGet configuration: `dotnet nuget add source <address> -n client-nuget -u <user> -p <token>` |

When a setting is empty, bootstrap lets the tool use its own configuration, and preflight checks that
configuration (it says "from pip configuration", "from npm configuration" or "from NuGet configuration"). When the
tool has no configuration either, the public sites are used.

Also set `COMPARE_PUBLIC_NUGET_FEED=false` in `backend\.env` when nuget.org is not reachable ("backend\.env").

The repositories you scan bring their own `nuget.config`; you configure nothing for them. If their feeds need a
login, the same account NuGet configuration (or a credential provider, such as Azure Artifacts') supplies it, and
the platform never sees or stores it. `01-ENVIRONMENT-SETUP.md` section 10, "NuGet feeds for scanned
repositories", has the details.

### Database


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

#### The schema name

The platform creates its own schema in that database (`DB_SCHEMA`, "backend\.env") and keeps every table in it. The
name must be:

- **lowercase** letters, digits and underscores only;
- starting with a letter or an underscore;
- at most 63 characters;
- **no hyphens, spaces or capitals.** `modplatform` and `mod_platform` are fine; `mod-platform` and `ModPlatform`
  are refused.

If the administrator creates the schema for you instead, they must make your login its owner, or grant it
`CREATE` and `USAGE` on it.

### The source folder and the platform folder

The platform arrives as our git repository; the client keeps it as a folder in its own. Three steps: clone ours into
the source folder, make your branch and the platform folder in the client's repository, and copy the source in.

#### 1. Clone our repository into the source folder

```powershell
git clone -c core.longpaths=true --branch master https://git.ourcompany.com/modernization-platform.git C:\MP\source
```

Installations follow our **master**: every commit on it has passed the full test suites. Tags are reference points
we create by hand for bigger milestones; nothing installs one. When master arrives as a bundle instead, clone the
bundle: `git clone -c core.longpaths=true --branch master C:\MP\delivery\master-<commit>.bundle C:\MP\source`,
after checking its hash as in "Appendix: upgrading from a bundle of master".

From now on, the source folder is only ever copied from (rule 1), and stays on master.

**When the client's environment cannot reach our git**, none of Part 1's copying happens on the client's machine: we
deliver the platform folder into the client's repository from our own machine, and the client's environment only
pulls its branch ("Delivering to a client from our machine", Part 2).

#### 2. Your branch and the platform folder in the client's repository

Clone the client's repository, if it is not on the machine yet, then create your own branch from the branch the
client names (here `main`), or check it out when it exists already:

```powershell
git clone -c core.longpaths=true https://git.client-a.example/team/shared.git C:\MP\client
```

```powershell
git -C C:\MP\client switch -c rohit/modernization-platform origin/main
```

```powershell
git -C C:\MP\client switch rohit/modernization-platform
```

(The second command creates the branch; the third checks out one that exists. Use one of them.) Then the platform
folder:

```powershell
New-Item -ItemType Directory C:\MP\client\modernization-platform
```

**At the root of a dedicated repository** ("Two layouts"), there is no folder to create: clone the client's
repository and check out its branch for the platform; the repository's root is the platform folder. The first copy
is easiest with the update script, which works from an empty folder or from a new repository's root alike, and
lists the host's own files it replaced:

```powershell
git clone -c core.longpaths=true https://git.client-b.example/team/platform.git C:\MP\platform
```

```powershell
powershell -ExecutionPolicy Bypass -File C:\MP\source\scripts\update-platform.ps1 -Source C:\MP\source -Platform C:\MP\platform -Branch main
```

It copies, writes `PLATFORM_SOURCE.json` and commits, so steps 3 and "Committing the platform folder" are done; push
the branch, then go on with "backend\.env".

#### 3. Copy the source in

Everything but `.git` (and nothing that is local to a machine):

```powershell
robocopy C:\MP\source C:\MP\client\modernization-platform /E /XD .git .venv node_modules /XF .env
```

robocopy's exit codes 0 to 7 mean success; 8 and above mean it failed. Then record which of our commits the folder
holds. Every preparation and verification names it, beside the client repository's commit:

```powershell
cd C:\MP\client\modernization-platform; powershell -ExecutionPolicy Bypass -File .\scripts\write-platform-source.ps1 -Source C:\MP\source
```

It writes `PLATFORM_SOURCE.json` (our commit, a tag only if one happens to point at it, the date) into the platform
folder, and prints the commit.

#### "detected dubious ownership"

If instead git prints:

```
fatal: detected dubious ownership in repository at 'C:/MP/client'
'C:/MP/client' is owned by:
        BUILTIN/Administrators (S-1-5-32-544)
but the current user is:
        CORP/jdoe (S-1-5-21-...)
To add an exception for this directory, call:

        git config --global --add safe.directory C:/MP/client
```

the copy kept the original owner (another account, or Administrators), and git will not work in a repository it
does not consider yours. Tell git this one folder is safe, for your account only, with exactly the command it
printed (forward slashes):

```powershell
git config --global --add safe.directory C:/MP/client
```

Then run the `git log` check again. Do the same for any client repository that shows the error ("Registering a client repository"). Do
not use `safe.directory '*'`: it switches the check off for every folder.

If the PowerShell scripts will not run ("running scripts is disabled on this system", or "is not digitally
signed"), the copy kept Windows' downloaded-file mark. Clear it for this folder only:

```powershell
Get-ChildItem C:\MP\client\modernization-platform -Recurse -File | Unblock-File
```

The commands in this guide start the scripts with `powershell -ExecutionPolicy Bypass -File ...`, which works
without changing any policy.

### backend\.env


Create it from the committed example:

```powershell
Copy-Item C:\MP\client\modernization-platform\backend\.env.example C:\MP\client\modernization-platform\backend\.env
```

```powershell
notepad C:\MP\client\modernization-platform\backend\.env
```

`backend\.env` is never committed and never copied anywhere by the platform. Every key:

| Key | Meaning | Example | Secret |
|---|---|---|---|
| `DB_HOST` | The PostgreSQL server | `pgsql01.client.com` | no |
| `DB_PORT` | Its port | `5432` | no |
| `DB_NAME` | The database from "Database" | `modernization` | no |
| `DB_SCHEMA` | The platform's schema ("Database" naming rules) | `modplatform` | no |
| `DB_USER` | The login from "Database" | `modplatform` | **yes** |
| `DB_PASSWORD` | Its password | (from the administrator) | **yes** |
| `RUNS_DIR` | Where all run output, worktrees, conversions and verifications go. Absolute, short, **outside** the platform folder and outside the client's repository (preflight warns) | `C:\MP\runs` | no |
| `STEP_TIMEOUT_SECONDS` | Optional, `3600`. How long any step may run before it is stopped ("Large repositories"). Per step and per repository: `python -m app.workflow.time_limits` | `3600` | no |
| `STEP_STALL_SECONDS` | Optional, `900`. How long a running step may report no progress before it is stopped as stalled, with where it was | `900` | no |
| `STEP_PROJECT_SECONDS` | Optional, `300`. Inside a step: how long loading one project may take before it is recorded "not checked", with the reason, and the step carries on | `300` | no |
| `STEP_FILE_SECONDS` | Optional, `60`. The same for one file | `60` | no |
| `REPOS_DIR` | Optional. Where repositories registered by their git URL are cloned: `<REPOS_DIR>\<engagement>\<repository>`. Absolute, short, outside the platform folder and outside `RUNS_DIR`. Empty: the registration form asks for the folder each time ("Registering a client repository") | `C:\MP\repos` | no |
| `API_HOST` | The address the backend listens on | `127.0.0.1` | no |
| `API_PORT` | Its port. Bootstrap writes the frontend's link to the backend from this | `8001` | no |
| `CORS_ORIGINS` | The frontend's address(es), comma-separated | `http://localhost:5174,http://127.0.0.1:5174` | no |
| `DEPLOYMENT` | `client`. **Never set it to `demo` on the VDI**: `demo` lets the demo-reset script delete every engagement and repository, and this database is the only copy of the client's data | `client` | no |
| `PIP_INDEX_URL` | "Package sources"; empty to use pip's own configuration | `https://artifactory.client.com/artifactory/api/pypi/pypi-remote/simple` | no (put a login in pip's own configuration, not here) |
| `NPM_REGISTRY` | "Package sources"; empty to use npm's own configuration | `https://artifactory.client.com/artifactory/api/npm/npm-remote/` | no |
| `NUGET_SOURCES` | "Package sources"; feed addresses or folders for building the step programs, comma-separated; empty to use the account's NuGet configuration | `https://artifactory.client.com/artifactory/api/nuget/v3/nuget-remote/index.json` | no |
| `COMPARE_PUBLIC_NUGET_FEED` | Whether dependency assessment also asks nuget.org which versions exist publicly. `false` where nuget.org is unreachable | `false` | no |
| `PYTHON` | The Python bootstrap and preflight use, as a full path. Empty: `python` on `PATH`. (The backend itself always runs in `backend\.venv`, which bootstrap builds with this Python) | `C:\MP\tools\python314\python.exe` | no |
| `DOTNET_ROOT` | **Only when .NET is installed per user** ("Account settings"): the folder it was installed into. The platform puts it first on `PATH` and sets `DOTNET_ROOT` for every process it starts. **Leave it empty** when the client installed .NET machine-wide | `C:\MP\tools\dotnet` | no |
| `SESSION_IDLE_MINUTES` | Optional, `240`. A signed-in session ends after this many minutes without use ("Users and sign-in") | `240` | no |
| `RESULTS_KEEP` | Optional, `3`. How many of each kind of result the database keeps per repository (and per engagement for the estate's), newest first; older ones are pruned. Run folders are never touched ("More than one person", "Shared results") | `3` | no |
| `VISUAL_STUDIO` | Optional. `off` removes "Open in Visual Studio" from file links. Empty: every Visual Studio 2022 or later edition found is offered ("Troubleshooting", "Checking which Visual Studio is used") | `off` | no |
| `VISUAL_STUDIO_PATH` | Optional. The `devenv.exe` of one Visual Studio installation, used in place of what detection finds: for a machine where detection picks the wrong one, or an installation the Visual Studio Installer does not list | `C:\Program Files\Microsoft Visual Studio\18\Enterprise\Common7\IDE\devenv.exe` | no |

Every key added later is optional and has a default, so an upgrade never requires editing this file ("Upgrade
notes" names each new one).

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

### Committing the platform folder and pushing your branch

Commit only the platform folder, on your own branch, and push your branch. `backend\.env`, `.venv`,
`node_modules` and the published step programs are ignored by the platform folder's own `.gitignore`, so they are
never committed:

```powershell
git -C C:\MP\client status --short -- modernization-platform
```

```powershell
git -C C:\MP\client add -A -- modernization-platform
```

```powershell
git -C C:\MP\client commit -m "Modernization platform: first copy" -- modernization-platform
```

```powershell
git -C C:\MP\client push -u origin rohit/modernization-platform
```

The `-- modernization-platform` on each command is what keeps everything else out (rule 2): the commit takes only
that folder, even if something else in the client's repository is staged. Check with
`git -C C:\MP\client show --stat HEAD`: every file listed starts with `modernization-platform/`.

### Preflight


Preflight checks everything this guide has set up and changes nothing. Run it with any Python: it checks the one
`PYTHON` names in `backend\.env` (else `python` on `PATH`), and the .NET that `DOTNET_ROOT` names (else `dotnet` on
`PATH`):

```powershell
cd C:\MP\client\modernization-platform; C:\MP\tools\python314\python.exe scripts\preflight.py
```


#### Reading it

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
- `WARNING` lines are worth knowing, but never fail. For example, a Python older than the one the full suite was
  tested on, 3.14.8.
- The **Proxy** lines show `HTTPS_PROXY`, `HTTP_PROXY` and `NO_PROXY`, any proxy set in pip's or npm's own
  configuration, and the Windows system proxy.
- Each **package source** line says where its address came from (`backend\.env`, or the tool's own
  configuration), whether it goes **through the proxy** or **direct**, and what the tool did. For example,
  "pip ... downloaded the pyyaml==6.0.3 wheel", or the tool's own error.
- The "Long paths" lines are `ON` or `OFF`, and never fail. `NOTE` lines are information only.
- Once the schema exists, the **platform** line says whether a platform holds it: `WARNING ... a platform holds this
  schema` while one runs (yours too: stop it before an upgrade), or a `NOTE` that the last one stopped without
  shutting down and its heartbeat has expired. "More than one person", "A stale heartbeat".
- **existing data** lines report data an older version allowed and a newer rule would refuse, such as one checkout
  registered in two engagements. They are left working and never changed ("Appendix: upgrading from a bundle of
  master").

Before bootstrap, the database section reports the database driver as missing: that is expected, bootstrap
installs it.

#### Fixing each MISSING item

| MISSING | Fix |
|---|---|
| Python ... too old / too new, or not found | Install a Python 3.11 to 3.14 ("Account settings"), and name it as `PYTHON` in `backend\.env` |
| Python ... is a pre-release (alpha, beta, release candidate) | Install the final release: "Troubleshooting", "Replacing a pre-release Python" |
| Node.js ... too old | Install Node.js 22.12 or later (or 20.19+) |
| npm ... too old | Comes with Node.js: update Node.js |
| .NET SDK: none of ... | Install a .NET 10 SDK ("Account settings"). A .NET 9 or a preview SDK does not count |
| .NET runtime for the step programs ... DOTNET_ROOT is not set | .NET is installed per user: set `DOTNET_ROOT` in `backend\.env` to the folder it names ("Account settings" and "backend\.env") |
| git ... too old / not found | Install git 2.17 or later, and open a new window |
| PIP_INDEX_URL / NPM_REGISTRY / NUGET_SOURCES ... failed: "Failed to resolve", "No such host is known", a timeout, "connection broken" | This machine cannot reach that address, or not through the proxy shown on that line. Find one it can ("Package sources"), or ask IT which proxy applies |
| ... failed: "401", "Unauthorized" | The source needs a login: give it to the tool's own configuration ("Package sources", "Where each one goes") |
| ... failed: "403", "Forbidden" | The login has no right to that source: ask its owner for read access |
| ... failed: "certificate verify failed", "unable to get local issuer certificate", "SSL" | A proxy or mirror re-signs connections with the client's own certificate, which the tool does not trust yet. Ask IT for the client's standard pip, npm and NuGet certificate settings; do not turn verification off |
| ... failed: "404", "Not Found", "could not find a version" | The address is wrong, often a missing `/simple` for pip or `/index.json` for NuGet, or the mirror lacks the package |
| If preflight's own run is blocked even though the tools work | "Troubleshooting", "When preflight's own check is blocked" |
| RUNS_DIR: not set / inside the repository / not writable | Set an absolute folder outside `C:\MP\client\modernization-platform` that you can write to ("backend\.env") |
| REPOS_DIR: not an absolute path / inside the platform's folder / inside RUNS_DIR / not writable | Set it to a short folder of its own, such as `C:\MP\repos`, or leave it empty ("backend\.env") |
| connection: ... | Check `DB_HOST`, `DB_PORT`, `DB_NAME`; a "password authentication failed" means `DB_USER` / `DB_PASSWORD`; a timeout means the VDI cannot reach the server (a firewall) |
| connection: ... (17 needed) | The server is not PostgreSQL 17: ask the administrator |
| schema ...: this login cannot create a schema | The login lacks `CREATE` on the database ("Database") |
| schema ...: exists, but this login cannot create tables in it | Ask the administrator to make the login the schema's owner |
| scratch schemas | The login lacks `CREATE` on the database ("Database") |

### Bootstrap


Bootstrap installs and sets up everything, in eight stages. It uses the Python `PYTHON` names in `backend\.env`
(else `python` on `PATH`) and the .NET `DOTNET_ROOT` names (else `dotnet` on `PATH`):

```powershell
cd C:\MP\client\modernization-platform; powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
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
| **1. Preflight** | "Preflight" without the database checks | under a minute | never (it only reads) |
| **2. Python virtual environment** | Creates `backend\.venv` with the Python you gave | under a minute | `backend\.venv` exists. To rebuild it with another Python, delete the folder and rerun |
| **3. Python dependencies** | Installs `backend\requirements.txt` into `backend\.venv`, from wheels only (`--only-binary=:all:`), so nothing is compiled | 1 to 3 minutes | `requirements.txt`, `PIP_INDEX_URL` and the Python are unchanged since the last install |
| **4. Preflight: the database** | "Preflight"'s database checks: connection, PostgreSQL 17, the right to create the schema and scratch schemas | seconds | never (it only reads) |
| **5. Frontend** | Writes `frontend\.env` (the backend's address, from `API_HOST` and `API_PORT`) if missing; installs the frontend's packages with `npm ci` | 1 to 2 minutes | `package-lock.json` and `NPM_REGISTRY` unchanged |
| **6. C# step programs** | Builds and publishes the six discovery programs into `steps\step-003-fingerprinting\publish\` with your .NET SDK | 3 to 10 minutes (the first restore downloads the build packages) | for each program: its sources, the SDK version and `NUGET_SOURCES` unchanged |
| **7. Migration** | Creates or updates every table in `DB_SCHEMA` (`alembic upgrade head`) | under a minute | nothing to do when already up to date |
| **8. Seed** | Loads the platform's configuration and the item catalog | under a minute | it changes only what changed, and never overwrites catalog edits made in the UI |

What failure looks like, and what to do:

| Stage | Failure | Usual cause |
|---|---|---|
| 1, 4 | `a prerequisite is missing (listed above as MISSING)` | the table in "Preflight" |
| 2 | `could not create backend\.venv` | The `-Python` path is wrong |
| 3 | `pip could not install ... from wheels` | The mirror is unreachable or needs a login ("Package sources"); "No matching distribution found" means the mirror lacks a package or a wheel for this Python ("Troubleshooting") |
| 5 | `npm ci failed` | The registry is unreachable or needs a login ("Package sources") |
| 6 | `dotnet publish of <program> failed` | NuGet feed unreachable or needing a login ("Package sources"), or no .NET 10 SDK. Run the command it prints to see the error |
| 7 | `alembic upgrade head failed` | The database login lost a right, or the schema belongs to another login |
| 8 | `python -m app.seed failed` | Read the message above it; rerun with `-Stage 8` |

**Everything else runs inside the backend's one Python environment.** Conversion preparation, verification, and
the vendored scripts under `third_party\code-modernization` are part of the backend and use `backend\.venv`.
Nothing needs installing separately for them, and there is no second Python environment to look after.

At the end bootstrap prints `Bootstrap complete` and the two commands of "Starting the backend and the frontend".

### Starting the backend and the frontend


Two PowerShell windows, each left open: they show the logs. Do not start them in the background.

**Window 1, the backend** (port 8001, `API_PORT`):

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
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
cd C:\MP\client\modernization-platform\frontend; npm run dev -- --port 5174 --strictPort
```

It is up when it prints `Local: http://localhost:5174/`. Open that address in the browser: the header shows
**Modernization Platform** with a green **connected** badge. A red **unreachable** badge means the backend is not
running, or `frontend\.env` points at another port.

### The first admin, and signing in

Every person signs in, and the platform knows who does what (Part 2, "Users and sign-in"). Once, at installation,
after bootstrap and before anyone signs in, create the first admin: the person setting the platform up, on this
machine. It asks for a password twice (12 characters or more):

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.users create-first-admin --login jdoe --name "Jane Doe"
```

It registers the Windows account running it and this machine's name; `--windows-account` and `--host` (repeatable)
name others. It refuses once an admin exists: after that, nobody makes themselves an admin by any route. Then start the
platform and sign in at `http://localhost:5174/` with that name and password. Everyone else asks for access from the
sign-in page of their own platform, and an admin approves it (Part 2, "Users and sign-in").

### Creating the engagement


An engagement is one client program, created by an admin, once, either way:

- **In the UI:** **+ New engagement**, beside the **View** selector at the top right. Fill in the client name and
  the target framework (the .NET version the estate moves to, such as `net10.0`); the id is filled in from the
  name. **Create engagement**, and the view switches to it.
- **From the command line** (the backend need not be running):

  ```powershell
  cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.engagements.cli create --name "Client A" --target-framework net10.0
  ```

  `--id` sets the id (default: made from the name, `client-a`); `--target-platform` and `--description` are
  optional. `python -m app.engagements.cli list` lists the engagements.

### Registering a client repository


The main way: give the platform the repository's git URL. Its discovery job clones the repository, then scans it,
and a later **Rescan** fetches the newest commits first. A repository you already cloned yourself can still be
registered by its folder (the end of this section).

#### Signing in to the client's git host, once

The platform runs git as you, with your own credentials: Git Credential Manager (installed with Git for Windows)
for an https URL, your SSH key for an SSH one. It never asks for, stores or logs a credential. It cannot answer a
sign-in prompt either, so a clone that needs a sign-in fails at once and says so. Sign in once, outside the
platform, in your own PowerShell window:

```powershell
git ls-remote https://git.client-a.example/team/OrderService.git
```

- **https:** Git Credential Manager opens its sign-in window (the client's single sign-on, or a personal access
  token if the git host asks for one). It remembers the sign-in for your account, so every later clone and fetch,
  including the platform's, uses it. The command then lists the repository's branches.
- **SSH** (`git@git.client-a.example:team/OrderService.git`): the first time, answer `yes` to the host's key. A key with a
  passphrase must be loaded into the ssh-agent (`ssh-add`), because the platform cannot type a passphrase.

When a clone fails with "needs a sign-in the platform cannot give", do this, then press **Rescan** on the
repository's page (or register again).

#### Register it

In the UI, choose the engagement in **View**, then **Repositories** → **+ Register Repository**. **Git URL** is
selected:

1. **Git URL:** `https://git.client-a.example/team/OrderService.git` (or `git@...`, `ssh://...`; a URL must not contain a
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
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.repositories.cli register-url --engagement client-a --url https://git.client-a.example/team/OrderService.git
```

`--branch` and `--target C:\MP\repos\client-a\OrderService` are optional, as in the form.

**While it clones**, the repository's row and page show `cloning` and git's progress ("Receiving objects: 45%").
The clone is full (every branch and its history, not shallow) with `core.longpaths=true`. A failure shows git's own
message and what to do, for example how to sign in. Discovery and preparation then follow, exactly as for a
folder.

If the repository's `nuget.config` names a feed by a relative folder (for example `..\EnterprisePackages\feed`),
place that folder beside the clone, exactly where the path points.

#### Rescan of a cloned repository

**Rescan** on the repository's page first fetches from its URL and fast-forwards its branch, then scans the commit
it reaches. A conversion that has not been run yet moves onto that commit; once one has been run, **Start the next
conversion** prepares a new one from it (below). The fetch refuses, changing nothing, when:
- the clone has local changes (edited files, even uncommitted ones): commit, stash or discard them outside the
  platform;
- the clone is on another branch than the one registered: switch it back;
- the branch has commits the remote does not have: resolve that outside the platform.

The conversions themselves live in worktrees under `RUNS_DIR`, on their own branches, so they never count as local
changes of the clone.

#### Registering a folder you cloned yourself

Choose **Local folder path** in the form instead:

```powershell
git clone -c core.longpaths=true https://git.client-a.example/team/OrderService.git C:\MP\repos\OrderService
```

1. **Local folder path:** `C:\MP\repos\OrderService`, then leave the field. The form inspects the folder and fills
   in the clone URL from its `origin` remote. A repository with no remote at all registers without one.
2. **Register & launch discovery.**

A folder registered this way is never fetched by the platform: pull new commits into it yourself before **Rescan**.
If git reports "dubious ownership" for a repository you copied rather than cloned, see "The source folder and the platform folder".

#### What discovery and preparation produce

Discovery runs every step on its own, and its last step, `conversion-preparation`, prepares the first conversion.
It takes from a few minutes to much longer for a large repository; the repository's page shows each step as it
finishes (**Executions** tab).

In the UI, on the repository's page, one tab at a time, in four groups: **Overview**; **Discovery** (Surface,
Projects & fingerprint, Dependencies, Dependency graph, Impact, Tests); **Modernization** (Work list, Conversion);
**Activity** (Executions, Details). Each tab has its own address (`/repositories/<id>/<tab>`), so it can be
bookmarked or sent, and the page reopens on the tab last used:

| Tab | Shows |
|---|---|
| Overview | size, projects, entry points, items found; and the key figure from each tab (work items, request entry points, dependencies and SOAP calls needing change, the conversion's state, the latest execution), each a link into its tab |
| Surface | what can call the repository, and what it calls. Each section folds on its own and says what is in it while folded; the bar at the top jumps to a section and expands or collapses them all, and the page remembers which are open |
| Dependency graph | the dependency graph: projects, packages and assembly references from the roots down, as a graph or a tree, with + and − to expand and collapse, search, transitive packages and filters (`37-DEPENDENCY-HIERARCHY.md` Part E) |
| Projects & fingerprint | solutions, projects, frameworks |
| Dependencies | every package: the version in use, the recommended version, its outcome and flags, and a **Reason** in plain words for each (the advisory, its severity and the version that fixes it; why an upgrade is safe; which shared framework provides it; the publisher's named successor; why a lookup did not answer, such as a feed returning 401). "Vulnerable" always refers to the version in use |
| Surface (SOAP compatibility) | each SOAP call per environment: the Runtime and Platform verdicts, a **Why** beside each (the matrix entry that decided it and its probe evidence, or why it is unknown), and whether a named person has **confirmed** that entry (reviewed its evidence and accepted it) |
| Work list | the catalog items found, where, and how each is to be resolved |
| Tests | test projects and what they cover |
| Executions | each discovery run, newest first, opening its step-by-step page |
| Details | the repository's registration, git facts and owner; Edit changes them |
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

### Moving an existing install that carries our .git

An install made before release 4 is a folder that is itself a clone of our repository, for example `C:\MP\code`,
with our `.git`. Moving it into the client's repository keeps all its data: the database schema, `RUNS_DIR`,
`REPOS_DIR` and the clones in it, and its `backend\.env`, which names them. Nothing in the database or `RUNS_DIR`
names the platform's own folder, so they carry over unchanged.

1. **Stop the old platform** ("Updating the platform", step 1): Ctrl+C in its backend's and frontend's windows,
   once no discovery or verification is running.
2. **Set up the new folders** as in "The source folder and the platform folder", but do not create a new
   `backend\.env`.
3. **Bring the old `.env` over:**

   ```powershell
   Copy-Item C:\MP\code\backend\.env C:\MP\client\modernization-platform\backend\.env
   ```

   If `RUNS_DIR` or `REPOS_DIR` in it is inside the old folder or inside the client's repository, see "backend\.env":
   both must be outside the client's repository. Leave the database keys as they are: the schema is the same one.
4. **Commit and push** ("Committing the platform folder and pushing your branch"). `.env` is not committed.
5. **Preflight and bootstrap** in the new folder ("Preflight", "Bootstrap"). Bootstrap applies any migrations the
   newer commit brings to the same schema, and republishes the step programs.
6. **Start the new platform** ("Starting the backend and the frontend") and check: the engagements, their
   repositories and their conversions are all there, and **Rescan** and **Verify** work.
7. **Delete the old folder**, only after that check, and only when no window has a file in it open:

   ```powershell
   Remove-Item -Recurse -Force C:\MP\code
   ```

---

## Part 2. Ongoing

### Updating the platform

How our newer work reaches the platform folder. Installations follow our **master**, the tip of it: every commit on
master has passed the full test suites, and unfinished work stays on a branch of ours until it does. Tags are only
reference points we create by hand for bigger milestones; the update neither needs nor installs one. Five steps,
every time:

1. **Stop the backend and the frontend.** Wait until no discovery or verification is running (the **Executions**
   tab), then press **Ctrl+C** in both windows. One still running when the backend stops is marked "orphaned by
   engine restart" the next time it starts, and must be started again.
2. **Run the update script.** It works the same run from the platform folder or from the source folder:

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\MP\client\modernization-platform\scripts\update-platform.ps1 -Source C:\MP\source -Platform C:\MP\client\modernization-platform -Branch rohit/modernization-platform
   ```

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\MP\source\scripts\update-platform.ps1 -Source C:\MP\source -Platform C:\MP\client\modernization-platform -Branch rohit/modernization-platform
   ```

   (Use one of them. The second runs the script as master has it, which the first update after a change to the
   script needs: see "Upgrade notes".) Add `-Push` to push your branch afterwards. The script:
   - stops, changing nothing, if the client's repository is not on your branch, or if the platform folder has
     uncommitted changes; it names the branch, or lists the files;
   - stops, changing nothing, unless the source folder is a clone of ours on `master`, following `origin/master`,
     with no commits of its own and no changes: the source folder is never a working repository;
   - updates your branch with `git pull --ff-only`; when it has commits in the platform folder, made since the
     latest delivery, that our repository has not imported, it lists them under a warning that this delivery
     overwrites their changes to our files, and carries on. To keep them, import them first ("Importing a client's
     changes"). Deliveries do not count;
   - fetches our master and stops, changing nothing, when it cannot tell which of our commits the platform folder
     holds: no `PLATFORM_SOURCE.json`, or a commit the source folder does not contain. The message says how to go
     on. (An empty platform folder is a first install, and needs none.);
   - **never goes backwards**: it stops, changing nothing in either folder, when master does not descend from the
     commit the platform folder holds or from the source folder's own master. That means our history was
     rewritten, or the platform was installed from another branch; the message says which, and lists the commits
     that would be lost. Ask us why before going on. `-AllowDowngrade` installs master anyway, after listing what
     is lost;
   - brings the source folder to master's tip with `git pull --ff-only`;
   - copies the source into the platform folder with robocopy, leaving out `.git`, `.venv`, `node_modules` and
     `.env`, and removes only the files we deleted or renamed: those in the installed commit and not in the new
     one. A file you committed in the platform folder is in neither: it is kept, and listed as "not part of the
     platform". A file of yours that one of ours of the same name replaces (at a repository's root, typically the
     host's own `README.md` and `.gitignore`) is listed as replaced;
   - writes the new `PLATFORM_SOURCE.json`: our commit, the one before (`previousCommit`), and a tag only if one
     happens to point at the commit;
   - stages and commits only the platform folder, with our source commit in the message; with `-Push`, pushes only
     your branch. Run again with nothing new on master, it commits nothing.

   Your local files are never touched: `backend\.env`, `frontend\.env`, `.venv`, `node_modules`, the published
   step programs, and anything you changed elsewhere in the client's repository (which stays uncommitted).
3. **Read the "Upgrade notes"** for every entry newer than the commit you had (`previousCommit` in the new
   `PLATFORM_SOURCE.json`). They list what needs doing besides bootstrap: a package your mirror must carry, a new
   setting, a rescan. Most updates need nothing more.
4. **Run bootstrap** ("Bootstrap"). It brings the dependencies, the step programs, the schema and the seed up to
   date with the new commit, and skips everything else. Only the admin's bootstrap changes the database, and records
   its new version; a developer's checks that their copy is at that version (below).
5. **Start the backend and the frontend** ("Starting the backend and the frontend"), and do any rescan the notes
   asked for.

Every commit on master can be applied this way to an installation of any earlier one, keeping all its data
(`CLAUDE.md` rule 15), with no need to go through the commits between; an upgrade note says so when one cannot.

#### Restarting

Run the two commands of "Starting the backend and the frontend" again. Nothing else is needed: the database and
`RUNS_DIR` keep everything.

#### Several developers: the admin updates first

Everyone's platform uses one database, so it has one version: our commit, recorded by the **admin's** bootstrap after
it migrates and seeds (`PLATFORM_SOURCE.json`'s on an installation, `HEAD` in our own repository). Every copy must be
at that version. So, every time:

1. **The admin updates first**: the five steps above. Their bootstrap migrates the database, seeds it, and records
   the new version.
2. **Then every developer** pulls the same update (steps 1 to 3), runs bootstrap and restarts. A developer's
   bootstrap never changes the database: it checks the version, and has nothing more to do.

What each one is told when the versions differ, by bootstrap and, in the same words, by a backend that refuses to
start:

| Message | Means | Do |
|---|---|---|
| "The admin has updated the platform: the database is at ... Pull the update first" | The database is newer than your copy | Pull the update, run bootstrap, start again |
| "This copy of the platform (...) is newer than the database (...): ask the admin to update first" | You pulled before the admin updated | Ask the admin to update; then run bootstrap again |
| "... at different versions, and which is newer cannot be told here" | Neither git, the migrations nor the commit dates say | Ask the admin which to use, and update so they match |

**In our own development repository** (no `PLATFORM_SOURCE.json`), commits come often, and most change nothing the
database holds. There the check compares only what the database depends on: the migration head, each step
registration's `version`, and a hash of the seed's data (`backend\app\seed\data`, `backend\app\jobs` and the catalog
export in `catalog\items`). A commit that changes none of these stops nobody and shows no banner; one that does says
which of them differs. The admin's bootstrap records them beside the commit. An installation always compares commits.

**While a backend runs**, it checks the database's version every 30 seconds. When the admin updates, the page shows a
banner, "The platform has been updated", saying what to do, and that backend refuses every change (409
`PLATFORM_UPDATED`) until its person pulls the update and restarts: reading, and signing in and out, go on.

A **first installation**, before any admin exists, migrates and seeds as the admin's does. An admin whose copy is
older than the database is stopped too: an older copy never takes the database back. To see both versions:

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.platform_version show
```

### Delivering to a client from our machine

A client's environment may have no access to our company git. Then our master reaches it through the client's own
repository: on **our** machine, `update-platform.ps1` copies master's files into a local clone of the client's
repository, commits only the platform folder on the client's branch, and pushes that branch with `-Push`. The
client's environment then pulls the branch and runs bootstrap, as the platform folder's `README.md` says.

**Why our history must never travel.** The client receives files, never our repository:
- our history and tags hold work for every client we serve: commits, messages and branches that name other
  engagements, and the platform's own history, which is ours, not the client's (CLAUDE.md rule 18);
- once pushed into a client's repository, history cannot be taken back: every clone, mirror and backup of that
  repository keeps it;
- a client needs the platform, not how it was made: `PLATFORM_SOURCE.json` records which of our commits the folder
  holds, which is enough to trace any question back to us.

So the source is a separate clone used only to copy from, the script copies files and never `.git`, and it pushes only
the client's branch (`refs/heads/<branch>`), never tags or any other ref. Never `git push --tags`, `--mirror` or
`--all` into a client's repository, never add our repository as a remote of theirs, and never merge or cherry-pick
between the two.

Two folders on our machine, short paths as in "Why paths must be short":

| Folder | What it is | Never |
|---|---|---|
| `C:\MPD\source` | **a separate, pristine clone of our repository**, on master, used only to copy from. The script pulls master in it | the repository we work in: the script refuses a source that is not on master following `origin/master`, or has commits or changes of its own |
| `C:\MPD\client-a` | a local clone of the client's repository, on the client's branch for the platform | anything of ours committed outside the platform folder |

#### First time

1. **The source clone**, once:

   ```powershell
   git clone -c core.longpaths=true --branch master https://git.ourcompany.com/modernization-platform.git C:\MPD\source
   ```

2. **The client's repository and its branch.** Clone it with the access the client gave us, and create the branch the
   client agreed for the platform (here `platform/modernization`) from the branch they name (here `main`):

   ```powershell
   git clone -c core.longpaths=true https://git.client-a.example/team/shared.git C:\MPD\client-a
   ```

   ```powershell
   git -C C:\MPD\client-a switch -c platform/modernization origin/main
   ```

3. **The platform folder, with master's files in it, committed.** As Part 1's "Copy the source in", from the source
   clone at master's tip:

   ```powershell
   git -C C:\MPD\source pull --ff-only
   ```

   ```powershell
   New-Item -ItemType Directory C:\MPD\client-a\modernization-platform
   ```

   ```powershell
   robocopy C:\MPD\source C:\MPD\client-a\modernization-platform /E /XD .git .venv node_modules /XF .env
   ```

   ```powershell
   cd C:\MPD\client-a\modernization-platform; powershell -ExecutionPolicy Bypass -File .\scripts\write-platform-source.ps1 -Source C:\MPD\source
   ```

   ```powershell
   git -C C:\MPD\client-a add -A -- modernization-platform; git -C C:\MPD\client-a commit -m "Modernization platform: first copy" -- modernization-platform
   ```

4. **Push only the branch**, then check what the client's repository received: no tag of ours, and no commit
   outside the platform folder.

   ```powershell
   git -C C:\MPD\client-a push origin refs/heads/platform/modernization:refs/heads/platform/modernization
   ```

   ```powershell
   git -C C:\MPD\client-a ls-remote --tags origin
   ```

   ```powershell
   git -C C:\MPD\client-a diff --stat origin/main platform/modernization -- . ":(exclude)modernization-platform"
   ```

   The last two print nothing.
5. **On the client's environment**, someone with access clones or pulls the branch and follows the platform folder's
   `README.md`: `.env`, preflight, bootstrap, start. Part 1 of this guide is the detail.

#### Each delivery after that

1. Bring the client's branch up to date and make sure the platform folder is clean (the script checks both):

   ```powershell
   git -C C:\MPD\client-a switch platform/modernization; git -C C:\MPD\client-a pull --ff-only
   ```

2. **Import first.** If the client committed changes in the platform folder, import them into our repository
   ("Importing a client's changes", below), and let master take them, before delivering. The update script delivers
   over changes that were never imported, overwriting them, and lists them under a warning.
3. **Run the update script** from the source clone, with `-Push`:

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\MPD\source\scripts\update-platform.ps1 -Source C:\MPD\source -Platform C:\MPD\client-a\modernization-platform -Branch platform/modernization -Push
   ```

   It pulls master into the source clone, refuses to go backwards, copies files only, removes what we deleted or
   renamed, writes `PLATFORM_SOURCE.json`, commits only the platform folder, and pushes only the branch ("Updating
   the platform" lists every check).
4. Check what went, as in step 4 above, then tell the client the update is on the branch, with any "Upgrade notes"
   entries newer than the commit they had. On their environment: stop the platform, `git pull` the branch, run
   bootstrap, start it again (the platform folder's `README.md`).

Nothing is run from the client's clone on our machine: no bootstrap, no backend. It exists only to receive master's
files and push them, and to import the client's changes.

### Importing a client's changes

A client may change the platform in its own copy, in either layout ("Two layouts"): `-Platform` names the platform
folder, or, for a dedicated repository, its root, where the whole repository is imported as the platform. Only the
client's commits since the latest delivery count, so a new repository's own first commit (its host's `README.md`
and `.gitignore`) never does. The changes may be a fix on the platform's branch, or a feature on a branch such as
`release/<feature>`. Those changes come back into our repository with `scripts\import-client-changes.ps1`, on our
machine, so our repository holds every feature, ours and every client's, and every installation receives them with
its next update. **The order is always: import first, then deliver.** A delivery made while the client's branch has
commits in the platform folder that were never imported overwrites their changes to our files: it lists them under a
warning, and carries on.

**The deny-list.** A plain text file on this machine, **outside** every repository (for example
`C:\MPD\deny-list.txt`): the terms that must never enter our repository, one per line, matched without regard to
case. Put in every client's name and short names, business units, application and repository codes, and host
names (CLAUDE.md rule 18). Lines starting with `#` are comments. The import refuses to run without it, with it
inside our repository, or with it empty.

**What it needs.** A local clone of the client's repository, on the branch to import, matching its remote, with a
clean platform folder (here `C:\MPD\client-a`, as in "Delivering to a client from our machine"), and our working
repository with no uncommitted changes. For the client's main branch, our working repository must be on master.

```powershell
git -C C:\MPD\client-a switch platform/modernization; git -C C:\MPD\client-a pull --ff-only
```

```powershell
powershell -ExecutionPolicy Bypass -File D:\work\modernization-platform\scripts\import-client-changes.ps1 -Platform C:\MPD\client-a\modernization-platform -Repository D:\work\modernization-platform -DenyList C:\MPD\deny-list.txt -Push
```

**Branch mapping.** The client clone's current branch decides where the changes go:

| Client's branch | Our branch |
|---|---|
| `main` or `master` | `master` |
| anything else, such as `release/<feature>` | the branch of the same name: updated when it exists, created from the commit the client received when not |

A branch name holding a deny-listed term is refused: it would enter our repository as a branch name.

**The merge rule.** Never a plain copy over our branch: it may hold work the client has not received yet, such as
a feature built for another installation, and a copy would revert it. Instead the import:
1. reads the commit the client received from `PLATFORM_SOURCE.json` (our repository must have it);
2. on a temporary branch from that commit, copies the client's committed folder over it, leaving out
   `PLATFORM_SOURCE.json`, `.env` files, `.venv`, `node_modules`, build output and everything else local-only, and
   removes the files the client deleted;
3. scans everything coming in (below), then commits it;
4. merges that commit into our branch. Where both sides changed the same lines, **the client's version wins**: the
   client is the source in this direction. Every file where that happened is listed, so it can be checked.

When an earlier import already took part of the client's changes, the next one starts from that import's commit, so
only what changed since comes in. The commit's subject is the client's latest commit message, its body lists the
client's other commits since the previous import, and a `Client-Commit:` trailer records the client's commit: the
next import starts there, and the update script knows what was imported.

**The scan.** Everything coming in is scanned: the added and changed lines, file names, the branch name and the
commit messages. It refuses, listing each finding with its file and line (a secret's value is never printed):
- secrets: sensitive keys with values (passwords, secrets, API keys, tokens), connection strings with passwords, URLs
  with passwords, private keys and known token formats;
- `.env` files committed in the platform folder (a local, ignored `.env` is simply never copied);
- binary files over 1 MB;
- every deny-list term.

Have the client remove what was found on their branch, rewriting the commit message if that is where it was, then
import again.

**master stays deployable.** When the target is master, the import runs every suite on the merged result
(`scripts\run-suites.ps1`: backend, frontend, C#, the step programs), and with `-Push` pushes master only when they
all pass. Otherwise master keeps the merge locally, unpushed, and the script says so: fix it with a commit on top,
run `scripts\run-suites.ps1`, then push. Any other branch is pushed once the scan passes. Without `-Push` nothing is
pushed.

**The report.** What was added, changed and deleted, every file where the client's version won, the commit, and
whether it was pushed. When the client has nothing new since the last import (or only our deliveries), it says so,
and changes nothing.

Then deliver as usual ("Delivering to a client from our machine", or "Updating the platform" on the client's
machine): the delivery brings the client's changes back to them together with everything else on master.

### Users and sign-in

Several developers each run their own platform (backend and frontend) on their own machine, against **one shared
database and schema**, so everyone sees the same engagements and repositories. Each person signs in, and every action
is recorded with who did it and from which machine.

**Signing in** needs three things to match the person's registration: their password, the Windows account their
platform's backend runs under, and their machine's name. Otherwise it is refused with a plain message, such as "This
account is not registered for this machine (DEVBOX-07) — ask the admin." **This deters shared credentials; it is not a
hard security boundary**: the platform runs on the person's own machine, which they control. A session ends when the
person signs out, or after `SESSION_IDLE_MINUTES` without use (240 by default, "backend\.env").

**Roles.**

| Role | May |
|---|---|
| **admin** | Everything: the master catalog, users, engagements, decisions, confirmations, workflow administration, and every repository |
| **developer** | Register repositories, and act on the ones they own. Everything else is read-only |

**Owners.** Whoever registers a repository owns it. Only its owner, or an admin, may rescan it, edit it, prepare and
verify its conversions, or delete it, and those that touch its folder only from the machine it was registered on (its
folder and run output are there). Everyone else sees it read-only: the repository page names the owner and disables
those actions, saying why. The backend enforces the same rules for every call, whatever the UI shows. A repository
registered before sign-in existed has **no owner** until an admin assigns one; until then only admins act on it.

**Asking for access.** Someone not registered starts their own platform and, on its sign-in page, chooses **Request
access**: they give their full name and choose a password (12 characters or more). Their Windows account and machine
are their platform's, taken from the machine, never typed; they sign in with their Windows user name (`asmith` for
`CORP\asmith`), which the page shows. Until an admin decides, they reach nothing, and the sign-in page says the request
is pending, or that it was rejected and why (they may then ask again). One request per Windows account waits at a
time.

A registered user on a **machine their registration does not name** asks the same way, **Ask to add this machine**,
giving their current password. Approving it adds the machine to their registration.

**Deciding requests** (admins): the header shows **N access requests** while any wait; it opens the **Users** tab,
where each request has **Approve** and **Reject** (with an optional reason, shown on the requester's sign-in page).
Approving always registers a **developer**. From the command line:

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.users requests
```

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.users approve --request 3f2a
```

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.users reject --request 3f2a --reason "Not on this programme"
```

`--request` takes the id `requests` prints, or its first characters; `requests --all` lists decided ones too.

**Making an admin** (admins): only an admin makes another user an admin, as an action of its own, recorded: **Make
admin** beside them in the Users tab, or `python -m app.users promote --login asmith`. No other route makes an admin:
registering, approving and editing a user always leave or make a developer.

**Registering a developer directly** (admins), for someone who cannot reach their sign-in page: the **Users** tab,
**Register a user**: their full name, the name they sign in with, their Windows account (`DOMAIN\user`, the account
their own platform runs under: `whoami` in their PowerShell window prints it), the machines they sign in from
(`hostname` prints it), and a temporary password. They choose their own password at their first sign-in. Or from the
command line, as an admin on your own machine:

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.users add --login asmith --name "Alex Smith" --windows-account CORP\asmith --host DEVBOX-07
```

**Changing a user** (admins): in the Users tab, change their machines (**change**, or **×** beside one machine to
remove just that one; their sessions there end), make an admin a developer again (**Make developer**), or reset their
password (temporary, replaced at their next sign-in; their sessions end). The command line does the same:
`python -m app.users set --login asmith --host DEVBOX-07 --host LAPTOP-12`, `remove-machine --login asmith --host
LAPTOP-12`, `set --login asmith --role developer`, `reset-password --login asmith`, and `list`. Their only machine
cannot be removed: disable them instead.

**Disabling, enabling and deleting** (admins):

- **Disable** takes effect at once: their open sessions end, and signing in is refused with "Your account is
  disabled: ask an admin to enable it". Their history and the repositories they own stay; the confirmation lists
  those, and you may give any of them a new owner at any time (**Assign** on its page). **Enable** restores access.
- **Delete** is refused while they own a repository: the refusal lists each one, to be given a new owner first.
  Afterwards the activity record still shows their name against everything they did.
- Nobody disables or deletes themselves, and nobody disables or deletes the last admin.

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.users disable --login asmith
```

`enable --login asmith` and `delete --login asmith` likewise; `set --deactivate` and `set --activate` still work, as
disable and enable.

Every request, approval, rejection, promotion, disabling, enabling, deletion and removed machine is recorded with who
and when ("Who did what", below).

**Assigning owners** (admins): on a repository's page, **Assign** (or **Change**) beside its owner; or list the
repositories and their owners, those with none first, and assign one:

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.users owners
```

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.users assign-owner --engagement client-a --repository orderservice --login asmith
```

**Command-line tools** act as the registered user whose Windows account and machine run them, and refuse otherwise:
registering and rescanning repositories, creating engagements, deletions, time limits, the engine allowlist and the
catalog export follow the same roles and ownership as the UI. Only `create-first-admin`, bootstrap, the seed and
preflight run without a registered user.

**Two people editing one record.** Decisions, item decisions, catalog items, matrix confirmations and an engagement's
settings carry a version. When two people edit the same one, the second to save is told that someone else changed it
first, who and when, and nothing is overwritten: reload, and make the change again.

**Who did what.** Every change (registrations, scans, decisions, confirmations, catalog edits, deletions, sign-ins)
is recorded with the person and their machine (`GET /api/activity`). Actions from before sign-in existed show as made
"before sign-in".

### More than one person

Each developer runs their own platform on their own machine; all of them use the same database and schema:

- **One platform backend per machine.** A running backend keeps a heartbeat for its machine. A second backend started
  on the same machine refuses to start before it touches anything, saying which process has it; backends on
  different machines run side by side. The header's **online** shows each machine with a running platform, and who
  is signed in there.
- **Jobs stay on their machine.** Every job records the machine that queued it, and a backend runs only its own
  machine's jobs. A backend that starts fails only its own machine's jobs left running. A job is resumed from the
  machine that queued it.
- **Each developer's own folders.** `RUNS_DIR`, `REPOS_DIR` and the clones they register are on their own machine:
  a repository's folder is only meaningful on the machine that registered it.
- **One checkout per engagement.** The platform creates its conversion branches (`conversion/1`, ...) and their
  worktrees in the registered checkout's git. So a checkout, or a worktree of it, is registered in one engagement
  only. Registering it in a second is refused, with the engagement that has it. To use the same repository in a
  second engagement, clone it again into another folder and register that.

#### Shared results

A repository's **owner scans it on their own machine**; the run output lands in that machine's `RUNS_DIR`. Everyone
else sees **every tab of its page, and the estate, in full**, from the database: no access to the owner's machine, no
copy of its files and no clone needed.

- **What is in the database.** Every result a tab or the estate reads is copied into the database as its step
  finishes: the repository inventory, solutions and projects, fingerprint, entry points, outbound calls, dependency
  assessment and graph, work list, tests, impact, and the estate's register, packages, dependencies, integration map,
  context map and SOAP report. So are each repository's conversions as its owner's platform last saw them, with each
  one's runbook and `VERIFICATION.md`.
- **What stays on the owner's machine.** Raw outputs no view reads: logs, timing profiles, SARIF exports and other
  intermediate files; a conversion's worktree and evidence files; the repository's own files. On another machine,
  wherever the UI offers one of those, it says where it is, **"on Ann's machine (DEVBOX-07)"**, instead of a link that
  cannot work. The repository's own files are opened from your own clone ("Your own clone of a repository", below).
- **A page at a time.** Every list that grows with a repository (entry points, invocations, packages, the work list
  and its occurrences, projects, impact work items and files, tests and test mappings, the estate's hosts, calls and
  packages) is served by the database 20 at a time, with its filter box matched there. A tab never loads a whole
  repository's result.
- **How long they are kept.** The newest **three** of each kind of result per repository (and per engagement for the
  estate's); older ones are pruned from the database after each scan. Set `RESULTS_KEEP` in `backend\.env` to keep
  more or fewer. The run folders on each machine are never touched.
- **The estate.** Estate consolidation reads only the database, so it covers every scanned repository of the
  engagement, whoever owns it and whichever machine scanned it. It remains an admin action.
- **Scans made before results were shared** are only in the run folder of the machine that made them. Their owner runs
  this once, on that machine, to copy them into the database (the newest `RESULTS_KEEP` of each kind; run folders are
  not changed; running it again copies nothing twice):

  ```powershell
  cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.results copy-existing
  ```

  `--repository <slug>` copies one repository (and its engagement's estate); `--dry-run` says what it would copy. A
  repository whose owner never runs it shows its results after its next scan: until then its page says that its
  results are only on its owner's machine.

#### Your own clone of a repository

The platform stores every file location relative to its repository (`src/Web/OrderService.cs`). Each person records
where their own clone of a repository is, on their own machine, and every file link on its page, and on its
executions' pages, joins that folder with the file's path: the owner and everyone else each open the same file from
their own clone. The owner's clone is the folder the repository was registered from; nothing to do.

Anyone else, on a repository's page:

1. The line under the header says **"No clone of yours is recorded on this machine"**, and a file link offers
   **Record your clone…** or **Copy the relative path**.
2. **Record your clone…** shows the command that makes one under `REPOS_DIR`, for example:

   ```powershell
   git clone -c core.longpaths=true https://git.client-a.example/team/OrderService.git "C:\MP\repos\OrderService"
   ```

3. Give the clone's folder, and **Record**. The platform checks that it is the top of a git clone of the **same
   repository** (the same remote URL; one cloned over https and one over ssh are the same) before recording it. A
   clone of another repository is refused, saying what it is a clone of.

From then on, file links open from your clone; **Change** beside the line records another folder, and **Forget my
clone here** removes the record (nothing on disk changes). Updating your clone is yours (`git pull`): a link opens
whatever your clone holds at that path.

#### A stale heartbeat

A running backend renews its heartbeat every 20 seconds, and **a heartbeat expires 90 seconds after it was last
renewed**. A heartbeat whose process no longer exists on the machine (a restart, a killed process) is taken over at
once. The age is measured on the database server's clock. When a backend refuses to start, its message says which
process holds the machine and how many seconds are left. Wait that long and start again, or, when you know that
backend has stopped, clear this machine's heartbeat:

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.heartbeat show
```

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.heartbeat clear
```

`show` lists the machines online and says whether this machine's heartbeat is live or expired. `clear` asks you to
type `clear` while it is still live, and refuses outright while its process is still running.

#### A second developer

Each developer sets up the platform on their own machine as in Part 1, with the **same database settings and schema**
(`DB_HOST` ... `DB_SCHEMA`) and their own `RUNS_DIR` and `REPOS_DIR`, on their machine. They do not run
`create-first-admin`: the first admin exists already. Their copy must be at the database's version, the admin's
latest update (`python -m app.platform_version show` says both), or bootstrap stops saying so ("Several developers:
the admin updates first"). They start their platform, choose **Request access** on its sign-in page, and sign in
once an admin approves it ("Users and sign-in").

### Deleting a repository or an engagement


**Delete** on a repository's page removes the repository from its engagement. **Delete engagement…** on the
Repositories page removes the engagement and every repository in it. Both are hard deletes and cannot be undone. The
same, from the command line:

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.deletion.cli repository --engagement client-a --repository orderservice
```

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.deletion.cli engagement --engagement client-a
```

Add `--dry-run` to see what would go without deleting anything.

**What goes:**
- every database row of it;
- its folders under `RUNS_DIR`;
- in each registered checkout, the worktrees the platform made and the branches the platform created (the ones
  its records name: `conversion/<n>`, experiment branches).

**What stays:**
- **the repository itself, however it was registered.** A clone the platform made from a git URL stays exactly where
  it is, like a folder registered by its path. Registering the same URL again later reuses that clone ("Registering a client repository");
- any branch the platform did not create, and any branch another registration of the same checkout also records
  ("More than one person");
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
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.deletion.cli audit
```

A repository can be registered again after its delete. Discovery and preparation start afresh, with no leftovers
in the way.

---

### Large repositories: progress, time limits and stopped steps

Discovery of a large legacy repository (well over a hundred projects, many solutions, large generated WCF proxy
classes) can take a while. Every step shows what it is doing, never waits forever, and can be resumed.

#### Watching a step

The repository's **Executions** tab shows, for the step that is running: how long it has run, its phase (such as
`load`, `index`, `detect`), the items done out of the total, and the project or file it is on. It changes at least
every 15 seconds. "last progress ... ago" appears when the step has reported nothing new for over 30 seconds.

Each step also writes, in its output folder under `RUNS_DIR` (the step's folder in the run, shown in its entry):

| File | Contents |
|---|---|
| `progress.json` | where the step is, or where it was when it ended |
| `timing-profile.json` | time per phase, the slowest projects and files, and anything "not checked", with the reason. **Paths and durations only, never code**: it can be shared with us without exposing client code |
| `stopped.json` | only after a time limit, a stall or a stop: why, and where the step was |

#### Time limits

| Limit | Default | When it is reached |
|---|---|---|
| Time limit | 3600 s (`STEP_TIMEOUT_SECONDS`) | the step is stopped, **TIMED_OUT** |
| Stall limit | 900 s (`STEP_STALL_SECONDS`) | the step reported no new phase, count or item for that long: stopped, **STALLED**, with where it was |
| One project | 300 s (`STEP_PROJECT_SECONDS`) | that project is recorded "not checked", with the reason; the step carries on with the rest |
| One file | 60 s (`STEP_FILE_SECONDS`) | that file is recorded "not checked", with the reason; the step carries on |

A stopped step ends with everything it started: no `dotnet`, MSBuild node, `git` or other process is left running.

The defaults are in `backend\.env`. An override for one step, for one repository, or for one step of one
repository is changed without code or a restart, and the most specific wins:

```powershell
cd C:\MP\client\modernization-platform\backend; .\.venv\Scripts\python.exe -m app.workflow.time_limits show --repository <engagement>/<repository>
```

```powershell
cd C:\MP\client\modernization-platform\backend; .\.venv\Scripts\python.exe -m app.workflow.time_limits set --step outbound-invocation-inventory --repository <engagement>/<repository> --timeout 7200 --note "a very large repository"
```

```powershell
cd C:\MP\client\modernization-platform\backend; .\.venv\Scripts\python.exe -m app.workflow.time_limits clear --step outbound-invocation-inventory --repository <engagement>/<repository>
```

`<engagement>/<repository>` is the engagement's id and the repository's slug, as in the repository's address in the
UI. Leave out `--step` for every step of that repository, or `--repository` for that step everywhere. The same is
available to scripts as `/api/workflow/time-limits`.

#### After a time limit, a stall or a crash

**Rescan** the repository. A rerun continues from the last project each step completed, as long as its inputs are
unchanged: projects already done are not analysed again. The step's message says how many it carried over.

A rerun never runs into the same wall twice. A project the stopped run recorded "not checked", or was still on after
60 seconds when it stopped, is not retried: it is recorded "not checked: not retried", with the reason, and the step
carries on with the rest. To retry them, once the cause is dealt with:

```powershell
cd C:\MP\client\modernization-platform\backend; .\.venv\Scripts\python.exe -m app.workflow.time_limits retry --repository <engagement>/<repository> --step outbound-invocation-inventory
```

then **Rescan**. Leave out `--step` for every step of that repository. Changing the project time limit
(`STEP_PROJECT_SECONDS`) also retries everything, from the start.

If the same step stops again, raise its limit for that repository (above), and send us its `timing-profile.json`
and `stopped.json`.

#### A record that does not conform

Every record a step writes is checked against its artifact's schema, and every required field must hold a value.
When one record does not conform, it is left out and recorded "not checked" on its project, naming the record and the
field, and the rest of the artifact is written. Send us the warning's text: it names code by path and id only.

#### Legacy projects without Visual Studio

Discovery reads project files and code as text: it never builds a project and needs neither Visual Studio nor the
.NET Framework build tools or reference assemblies. The one exception is dependency assessment's transitive
packages (`include_transitive`, off by default), which restores each project: a project that cannot be restored
there is recorded with the reason, within its own time limit.

### Troubleshooting


| Symptom | Cause | Fix |
|---|---|---|
| Updating: **"The argument '...\update-platform.ps1' to the -File parameter does not exist"** | The client's repository is on a branch that has no platform folder (often `main`), so the script is not on disk | Switch back to your own branch, `git -C C:\MP\client switch rohit/modernization-platform`, and run the update again ("Updating the platform") |
| Updating: **"Stopped: the client repository ... is on branch '...', not '...'"** | The client's repository is on another branch that does carry the platform folder | Switch to your own branch, as the message says. Never update or commit on anyone else's branch |
| Updating: **"Stopped: the platform folder has uncommitted changes"** | A file in the platform folder was edited and not committed (the message lists them) | Commit it to your branch if it must stay (it is then imported into the platform: "Importing a client's changes"), or discard it (`git -C C:\MP\client checkout -- modernization-platform/<file>`), then update again |
| Updating: **"Warning: the client's branch has N commit(s) in the platform folder that our repository has not imported"** | Changes were committed in the platform folder since the latest delivery, and not imported. The delivery went ahead and overwrote their changes to our files | To keep them, import them ("Importing a client's changes": the commits listed are still in the branch's history), then update again |
| Updating: **"Stopped: the source folder has changes"** | Something was run or edited in the source folder | Discard it as the message says. Nothing is ever run in the source folder |
| Updating: **"Stopped: the source folder is on a commit of its own (...), not master"** | An older copy of the update script left the source folder at a release tag | Put it back on master, `git -C C:\MP\source switch master`, and run the update from the source folder ("Upgrade notes", 2026-10-26) |
| Updating: **"Stopped: master (...) does not descend from the installed commit ..."** | Our master's history was rewritten, or the platform was installed from another branch. Nothing was changed | Ask us why, with the commits the message lists. Only when we confirm, run the update again with `-AllowDowngrade` |
| Updating: **"Stopped: the platform folder has files but no PLATFORM_SOURCE.json"**, or **"... which the source folder does not contain"** | The update cannot tell which of our commits the folder holds, so it cannot tell a file we deleted from one of yours. Nothing was changed | Do what the message says: record the commit the folder was copied from (ask us which), or bring that commit into the source folder; then update again. `-AllowDowngrade` does not get past this |
| Updating: **"... failed: git pull --ff-only"** | Your branch on the server has commits this machine does not, which cannot be fast-forwarded | Ask whoever else pushed to your branch; nobody else should. Then `git -C C:\MP\client pull --rebase` and update again |
| A feed answers **401** (preflight "HTTP 401", bootstrap stage 6, or a package marked "unknown ... 401 (Unauthorized)" in Dependencies) | The feed needs a login and none was supplied | Add the feed with its login to the account's NuGet configuration: `dotnet nuget add source <address> -n <name> -u <user> -p <token>`; for a feed a scanned repository names, `dotnet nuget update source <name> -u <user> -p <token>`, or install the client's credential provider and sign in once. Leave `NUGET_SOURCES` empty when the login is in the NuGet configuration |
| A feed answers **403** | The login is known but has no right to that feed | Ask the feed's owner for read access for that account; the address and the login are right |
| Stage 3: "No matching distribution found" or "Could not find a version that satisfies the requirement" | The mirror has no wheel of that package for this Python (bootstrap never compiles) | Use a Python 3.11 to 3.14 that the mirror has wheels for (3.13 is the safest), or ask for the mirror to include wheels for `cp314-win_amd64`. Never install a compiler for this |
| git: **"Filename too long"** | The path is over 259 characters and `core.longpaths` is off | `git config --global core.longpaths true` ("Account settings"), use shorter folders ("Before starting"), then clone again |
| A discovery step fails at once: **"You must install .NET to run this application"** | .NET is installed per user and `DOTNET_ROOT` is not set in `backend\.env` | Set `DOTNET_ROOT` ("Account settings" and "backend\.env"), restart the backend |
| The backend: **"[Errno 10048] ... only one usage of each socket address"**; the frontend: **"Port 5174 is already in use"** | Something already listens on that port, often an earlier window still running | Find it: `Get-NetTCPConnection -LocalPort 8001 -State Listen | Select-Object OwningProcess`, then `Get-Process -Id <id>`. Close that window. To use another port instead, change `API_PORT` (and rerun bootstrap with `-Stage 5` after deleting `frontend\.env`) or the frontend's `--port` and `CORS_ORIGINS` together |
| Conversion section: **"package step skipped: the baseline did not pass: ..."** | The repository does not build, or its tests fail, before any change | Nothing is lost: the conversion is prepared, and its package changes go to the agent as instructions in the runbook. Fix the build in the client repository if it should pass, then **Rescan** |
| **"package step skipped: no package step: test-coverage-assessment found no unit test project"** | The repository has no unit tests, so package upgrades cannot be checked by running them | As above: the package changes are left to the agent, with instructions |
| A step fails with "executable not found" | The step programs are not published | `bootstrap.ps1 -Stage 6 -Force` |
| A repository's tabs are empty, with **"Results of scans made before they were kept in the database ... are only in the run folder of the machine that made them, on Ann's machine (DEVBOX-07)"** | It was scanned before results were shared, and its owner has not copied them yet | Its owner runs `python -m app.results copy-existing` on that machine ("Shared results"), or rescans it |
| A file link, a log, an evidence file or an artifact says **"on Ann's machine (DEVBOX-07)"** | It is a file on the machine that scanned the repository: only the results the views read are shared | Nothing to fix. Ask its owner for the file if you need it |
| An edit is refused with **428 "does not say which version ... it changes"** | A script or tool called the API without the version of the record it edited | Send the version you loaded in `If-Match` (the record's `version`, or `edit_version` for a catalog item); 0 when it did not exist yet |
| A step ends **TIMED_OUT** or **STALLED** ("where it was: phase ..., 41 of 170, at ...") | The repository is larger than the step's limit allows, or one project or file is pathological | **Rescan**: it continues from the last completed project. If it stops again, raise the limit for that repository ("Large repositories: progress, time limits and stopped steps") and send us `timing-profile.json` and `stopped.json` from the step's folder |
| A step's message says **"... not checked: not retried"** | An earlier run that stopped (a time limit, a stall, a crash) recorded that project, or was stuck on it | Deal with the cause (raise the limit for that repository), run `python -m app.workflow.time_limits retry` ("After a time limit, a stall or a crash"), then **Rescan** |
| A step's message says **"... item(s) not checked"** | A project or file took longer than `STEP_PROJECT_SECONDS` or `STEP_FILE_SECONDS` | The rest is complete. The items and reasons are in `timing-profile.json` and in the step's warnings (`NOT_CHECKED`). Raise the limit and **Rescan** to check them |
| The UI loads, but every request fails | `frontend\.env` points at another port, or the frontend is not on 5174 (`CORS_ORIGINS`) | Start the frontend exactly as in "Starting the backend and the frontend" |
| A job shows **"orphaned by engine restart"** | The backend was stopped while it ran | Rescan the repository (or Verify again) |
| Preflight: **"Python: 3.14.0b2 ... is a pre-release"** | Software Center (or a download) gave an alpha, beta or release candidate | Replace it with a final release: "Replacing a pre-release Python", below |
| Registering by URL: **"... needs a sign-in the platform cannot give"** | git has no stored sign-in for that host, or no SSH key it can use without a passphrase | Sign in once outside the platform ("Registering a client repository", "Signing in to the client's git host, once"), then **Rescan** |
| Registering by URL: **"... exists and is not empty"** or **"is already a clone of another repository"** | The target folder holds something else | Choose another target folder, or empty it. An existing clone of the same URL is used as it is |
| Rescan of a cloned repository: **"has local changes"**, **"is on ... but this repository is registered on ..."**, **"cannot be fast-forwarded"** | Someone edited the clone, switched its branch, or committed in it | Commit, stash or discard the change, switch back, or resolve the divergence, outside the platform; then **Rescan** ("Registering a client repository"). Nothing was changed |
| Delete: **"Some files could not be removed, so nothing was deleted from the database"** | A program holds a file under `RUNS_DIR` open, usually Visual Studio with a conversion's worktree | Close it and delete again; it picks up where it stopped ("Deleting a repository or an engagement") |
| **"Open in Visual Studio"** opens another program, fails, or is missing | Detection found another installation than expected, or none | Run the detection report ("Checking which Visual Studio is used", below). Set `VISUAL_STUDIO_PATH` to the `devenv.exe` to use, and restart the backend |
| Catalog page: **"N items edited on this installation"** | Catalog items were edited in the UI here, so they differ from the catalog files the platform was updated with | Nothing is broken. The platform folder changes only through updates, so these are never exported into it or committed. To have them in the platform for everyone, **Download the edited items** (or run the command the page shows) and send the files to us |
| Sign-in: **"This account is not registered for this machine (...) — ask the admin."** | The machine's name is not among the person's machines | An admin adds it: Users tab, or `python -m app.users set --login <name> --host <machine>` (every machine they use) |
| Sign-in: **"This account is registered for the Windows account ..., and this platform runs as ..."** | The platform was started under another Windows account than the person's, or someone is signing in on another person's platform | Each person signs in only on the platform running under their own Windows account. If their account changed, an admin updates it ("Users and sign-in") |
| A button is disabled: **"Only this repository's owner, ..., or an admin may do this."** | The repository is someone else's | Ask its owner, or an admin to change its owner ("Users and sign-in") |
| **"This repository was registered on ...: its folder and run output are on that machine"** | Rescans, conversions and deletion touch the repository's folder, which is on the machine that registered it | Do it from the platform on that machine |
| **"Not saved: someone else changed ... first"** | Two people edited the same record; the other saved first | Reload, and make the change again: nothing was overwritten |
| A command: **"No user is registered for the Windows account ..."** | Command-line tools act as the registered user running them | Register the person ("Users and sign-in"), with this machine |
| The backend: **"Another Modernization Platform backend is already running on this machine"** | A second backend on the same machine | Use the one running, or stop it first ("More than one person", "A stale heartbeat") |
| Registering: **"This checkout is already registered in engagement ..."** | One folder (or a worktree of it) is in another engagement already | Clone the repository again into another folder and register that ("More than one person") |

#### Checking which Visual Studio is used

File links offer each Visual Studio installation the Visual Studio Installer lists that is a real edition
(Community, Professional or Enterprise) of 2022 or later, with the editor, whose program is `devenv.exe`. Other
products the installer lists are never used, even those built on the Visual Studio shell: SQL Server Management Studio
22, Build Tools. With several editions, the menu beside a file link lists each by its full name ("Visual Studio
Enterprise 2026", "Visual Studio Enterprise 2022"); the one chosen is remembered in the browser, and the newest is the
default. A file opens in a running instance of that installation, found through its own versioned automation (for
2026, `VisualStudio.DTE.18.0`), or in a new one.

To see what detection finds on a machine, without opening anything:

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.editors
```

It lists each installation with its name, version and program, `ACCEPTED`, or `REFUSED` with why, then what the UI
offers, newest first. If it picks the wrong one, or misses one, set `VISUAL_STUDIO_PATH` in `backend\.env` to the
`devenv.exe` to use; to remove the option, `VISUAL_STUDIO=off` ("backend\.env"). Restart the backend after either.

#### Replacing a pre-release Python

A pre-release (`3.14.0b2`, `3.14.0rc1`) is refused by preflight. Packages with compiled parts (pydantic-core,
psycopg) publish wheels for final releases, and an interpreter that is still changing can break them. On one VDI,
pydantic failed in bootstrap stage 7 on 3.14.0b2.

1. Install a final release, for example 3.14.8, per user ("Account settings"), or ask Software Center for the final release.
   The pre-release can stay installed: nothing uses it once `PYTHON` names the new one.
2. Name it in `backend\.env`: `PYTHON=C:\MP\tools\python314\python.exe`.
3. Delete `backend\.venv` (it was built with the pre-release), then run preflight and bootstrap again. Bootstrap
   rebuilds the environment with the final release and installs the locked versions into it.

#### When preflight's own check is blocked

Preflight runs each check with pip, npm and dotnet themselves, so it sees what bootstrap will see. If preflight
still cannot complete on a machine where the tools themselves work, run bootstrap's stages one at a time, without
stage 1, and stop at the first that fails. Stage 1 is preflight; each later stage does its own work and says
plainly when it fails.

```powershell
cd C:\MP\client\modernization-platform; foreach ($s in 2..8) { powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -Stage $s; if ($LASTEXITCODE -ne 0) { Write-Host "Stopped at stage $s"; break } }
```

Stage 4 is preflight's database check. If that is the part that is blocked, leave it out:

```powershell
cd C:\MP\client\modernization-platform; foreach ($s in 2, 3, 5, 6, 7, 8) { powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -Stage $s; if ($LASTEXITCODE -ne 0) { Write-Host "Stopped at stage $s"; break } }
```

Stage 7 (the migration) then shows whether the database works.

#### The ".NET Host" compliance warning

On a managed VDI, the client's endpoint security or compliance agent may raise a warning naming **.NET Host**
(`dotnet.exe`) when the platform runs it, typically when .NET is installed per user ("Account settings") rather than through
Software Center.

**What it means.** The agent sees an executable it does not manage running from the user's profile. `dotnet.exe` is
Microsoft's own, signed program: the same .NET that Software Center would install. The platform runs it for every
build, test and discovery step, so the warning appears whenever those run.

**What to do.** Do not try to silence or work around the agent. Raise it with the client's IT or security team,
naming the folder (for example `C:\MP\tools\dotnet`) and the version. Ask them either to allow that per-user
installation, or to install a .NET 10 SDK machine-wide through Software Center. In the second case, leave
`DOTNET_ROOT` empty in `backend\.env` and run bootstrap again.

---

### Appendix: upgrading from a bundle of master

For **our own installs only**: a platform folder that is itself a clone of our repository (with our `.git`),
such as `C:\MP\code`. A client install, in a folder of the client's repository, is updated with
`scripts\update-platform.ps1` ("Updating the platform").

**Every commit on master upgrades an existing installation in place and keeps all its data**: the database schema,
`RUNS_DIR`, the clones, `backend\.env` and `frontend\.env`. Its migrations only add to the schema or extend it, never
drop or rewrite what is there, and every new setting is optional with a default, so `backend\.env` needs no edit.
Data an older version allowed and a newer rule would refuse (such as one checkout registered in two engagements
before release 2) is reported by preflight and in the backend's log, and left working, never changed or deleted.
An upgrade that cannot be made in place says so in "Upgrade notes", with the reason; none so far.

When the machine cannot reach our git, master arrives as a git bundle, `master-<commit>.bundle`, with
`master-<commit>.bundle.sha256` beside it. We make one from master when asked (`scripts\master-bundle.ps1`). The
commands below upgrade `C:\MP\code` from `C:\MP\delivery`, with the bundle's name in place of
`master-<commit>.bundle`. An installation of any earlier commit, release tags included, is upgraded straight to the
bundle's: there is no need to go through the ones between. Run them in one PowerShell window, in order.

1. **Stop the platform.** Wait until no discovery or verification is running (the **Executions** tab), then press
   **Ctrl+C** in the backend's window and in the frontend's.
2. **Back up the schema.** Ask the database administrator for a backup of `DB_SCHEMA` first. The upgrade only adds
   to it, but a backup costs little.
3. **Check the bundle arrived intact.** The two lines must be identical:

   ```powershell
   (Get-FileHash -Algorithm SHA256 C:\MP\delivery\master-<commit>.bundle).Hash.ToLower()
   ```

   ```powershell
   (Get-Content C:\MP\delivery\master-<commit>.bundle.sha256).Split(' ')[0]
   ```

4. **Check the platform folder has nothing of yours in it.** git must print nothing (your `.env` files, `.venv`,
   `node_modules` and published programs are ignored by git and stay):

   ```powershell
   git -C C:\MP\code status --porcelain --untracked-files=no
   ```

   If it lists files, they were edited by hand: copy them aside, then `git -C C:\MP\code checkout -- .`.
5. **Bring master in, never backwards:**

   ```powershell
   git -C C:\MP\code fetch C:\MP\delivery\master-<commit>.bundle master
   ```

   ```powershell
   git -C C:\MP\code merge-base --is-ancestor HEAD FETCH_HEAD; $LASTEXITCODE
   ```

   The second command must print `0`: the bundle's master descends from what is installed. `1` means installing it
   would go backwards (our history was rewritten, or this install came from another branch): stop, and ask us.
   Then switch to it:

   ```powershell
   git -C C:\MP\code -c core.longpaths=true switch -C master FETCH_HEAD
   ```

   ```powershell
   git -C C:\MP\code log -1 --format="%h %d"
   ```

   The last command shows the bundle's commit and `HEAD -> master`. An install made from a release tag was in
   "detached HEAD" state; from now on it is on master.
6. **Read the "Upgrade notes"** for every entry newer than the commit you had.
7. **Preflight:**

   ```powershell
   cd C:\MP\code; C:\MP\tools\python314\python.exe scripts\preflight.py
   ```

   (your `PYTHON`, as in "Preflight"). Fix anything `MISSING` ("Preflight"). Read any `WARNING ... existing data` line:
   it is reported, not a failure.
8. **Bootstrap:**

   ```powershell
   cd C:\MP\code; powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
   ```

   It updates only what changed and skips the rest. It ends with `Bootstrap complete`.
9. **Start the platform** ("Starting the backend and the frontend"), and do any rescan the notes asked for. Your
   engagements, repositories, conversions and verifications are all there.

If the platform folder was installed without `.git` (step 5 fails with "not a git repository"), clone the bundle
into a new folder instead, copy `backend\.env` and `frontend\.env` into it, run steps 6 to 9 there, and start the
platform from the new folder. It uses the same schema and `RUNS_DIR`, so the data is the same:

```powershell
git clone -c core.longpaths=true --branch master C:\MP\delivery\master-<commit>.bundle C:\MP\code2
```

---

## Upgrade notes

Newest first. Each entry is dated and names the commit of ours that brought the change. It lists only what needs
doing after an update besides bootstrap: a rescan, a package your mirror must carry, a setting, an edit to make by
hand. Everything else an update brings, bootstrap applies by itself. Apply every entry newer than the commit you
had (`previousCommit` in `PLATFORM_SOURCE.json` after the update; in our own installs, the commit before step 5 of
the appendix), oldest of them first. Entries up to 2026-10-23 were the notes of releases 2 to 7, which are named so.

#### 2026-10-30, 46932fb: conversion preparation and configuration values

A repository whose last conversion preparation failed — the Conversion section shows "Last preparation" in red, for
example `SecretFound` for a binding name or host name a SetParameters file sets, or a `TypeError` on a .NET Framework
repository — gets no new conversion by itself. After updating, **on the machine that owns it**, either press **Start
the next conversion** on its Conversion section, or rescan it (**Rescan**, or `python -m app.repositories.cli
discover --engagement <engagement> --repository <repository>`): preparation runs again and now completes. Where a generated input would have quoted a secret value, it
names it by file, key and line instead, and the Conversion section shows that as a warning. Nothing else needs doing:
no setting, no migration.

#### 2026-10-27, eb3e4c5: the admin updates first; your own clone

From this update on, **the admin updates first, then every developer pulls and restarts** ("Several developers: the
admin updates first"):

1. **The admin** updates and runs bootstrap. Only the admin's bootstrap migrates and seeds, and it records the
   platform version in the database. This update's migration also moves stored file locations to paths relative to
   the repository, and records each repository's folder as its owner's clone; nothing is lost.
2. **Every developer** then pulls the update, runs bootstrap and restarts their backend. A developer's bootstrap
   never changes the database: it checks the version and stops, saying "the admin has updated; pull the update first"
   when the database is newer, or "ask the admin to update first" when their copy is newer. A backend on a different
   version from the database's refuses to start with the same message. A backend that was running when the admin
   updated shows a banner and refuses changes until it is restarted on the new version.

To open files of a repository you do not own, record your own clone of it from its page ("Your own clone of a
repository"). `backend\.env` needs no edit.

#### 2026-10-27, ecf45ee: shared results

After updating and running bootstrap, **on every machine that has scanned repositories**, copy the results of its
earlier scans into the database, once ("More than one person", "Shared results"):

```powershell
cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.results copy-existing
```

Until a machine's owner runs it, someone else opening a repository scanned there sees a note that its results are
only on that machine; the next scan of the repository stores them anyway. Nothing else needs doing: existing data and
run folders are kept, `backend\.env` needs no edit (`RESULTS_KEEP` is optional, `3`), and every view reads the same
results as before, now from the database and a page at a time. An edit that does not say which version it changes is
now refused (428): the UI always says, and command-line tools read the current version and send it.

#### 2026-10-27, 647d809: sign-in, roles and repository owners

After updating and running bootstrap, nobody can use the platform until these are done, in this order:

1. **Create the first admin**, once, on the machine where the platform runs (it asks for a password, 12 characters
   or more), then start the platform and sign in with it ("The first admin, and signing in"):

   ```powershell
   cd C:\MP\client\modernization-platform\backend; .venv\Scripts\python.exe -m app.users create-first-admin --login jdoe --name "Jane Doe"
   ```

2. **Register every developer**: the **Users** tab, with each person's Windows account and machines, or
   `python -m app.users add` ("Users and sign-in"). Command-line tools, such as registering or rescanning a repository,
   also need the person running them to be registered.
3. **Assign owners to existing repositories.** Repositories registered before this update have no owner, so only
   admins can rescan them, prepare and verify their conversions, or delete them, until an admin assigns one: on each
   repository's page (**Assign**), or `python -m app.users owners`, then `python -m app.users assign-owner` for each.
   Preflight says how many have none.

Nothing else needs doing: existing data is kept, earlier actions are recorded as made "before sign-in", `backend\.env`
needs no edit (`SESSION_IDLE_MINUTES` is optional), and the existing `frontend\.env` keeps working. Several people
can now share one database and schema, each on their own machine ("More than one person"); people who had a schema
each before keep working as they were.

#### 2026-10-26, c16f9c1: installations follow master

- **The first update after this change runs from the source folder.** The copy of `update-platform.ps1` in the
  platform folder still looks for release tags, and an update made with it left the source folder at one. Put the
  source folder back on master, then run the script from the source folder, which has the new one ("Updating the
  platform", the second command):

  ```powershell
  git -C C:\MP\source switch master; git -C C:\MP\source pull --ff-only
  ```

  ```powershell
  powershell -ExecutionPolicy Bypass -File C:\MP\source\scripts\update-platform.ps1 -Source C:\MP\source -Platform C:\MP\client\modernization-platform -Branch rohit/modernization-platform
  ```

  After that, either folder's copy works. `-Release` is gone; the newest master is always installed, never
  backwards.
- **Delivering from our machine**: the same, with `C:\MPD\source` ("Delivering to a client from our machine").
- **Our own installs**: bundles are made from master now, and installed as in "Appendix: upgrading from a bundle of
  master"; an install made from a release tag moves onto master there.

#### 2026-10-23, e58db01: catalog wording that cited a client's findings

- If bootstrap's stage 8 prints `CONFLICT catalog_items serilog-file-sink` or `CONFLICT catalog_items
  wcf-nettcp-client`, that item's description was edited in the UI, so the corrected wording was not applied. Open
  the item in the catalog and rewrite its description in general terms yourself. An item nobody edited takes the
  corrected wording by itself.

#### 2026-10-23, e98ed48 (release 7): the dependency graph

- **Packages**: bootstrap's stage 5 installs React Flow (`@xyflow/react`) and dagre (`@dagrejs/dagre`), both MIT.
  They must be available from `NPM_REGISTRY` like the others ("Package sources").
- **Rescan** each repository scanned before the update: it shows no dependency graph until then.

#### 2026-10-21, 81e188a (release 6): frontend component tests

- **Packages**: bootstrap's stage 5 installs the frontend's test packages (vitest, jsdom, @testing-library/react,
  @testing-library/dom, @testing-library/user-event). They must be available from `NPM_REGISTRY` like the others
  ("Package sources").

#### 2026-10-19, b79a96e (release 5): progress and time limits

- **Settings**, optional: `STEP_TIMEOUT_SECONDS` (3600, as before), `STEP_STALL_SECONDS`, `STEP_PROJECT_SECONDS`
  and `STEP_FILE_SECONDS` ("backend\.env"), with per-step and per-repository overrides ("Large repositories:
  progress, time limits and stopped steps"). Set them only for repositories that need longer.
- **Rescan** each repository scanned before the update. A web project holding other projects in its subfolders no
  longer counts their entry points, calls and findings as its own, so its counts may go down, by the duplicates.
  Until then, Surface says the scan used an older entry-point manifest (1.3.0).

#### 2026-10-17, 24eef78 (release 3): WCF client platform matrix 1.2.0

- **Rescan** each repository with SOAP calls: until then its SOAP report says the run used an older matrix than the
  newest. Matrix 1.2.0's Linux entries for basicHttpsBinding Transport/None and Transport/Certificate were confirmed
  with the server trusted by pinning its certificate's thumbprint; in production the container must trust the
  services' issuing certificate authority.

#### 2026-10-16, 78c9cd8 (release 2): locked packages, registering by URL

- **Packages**: bootstrap's stage 3 installs the exact versions in `backend\requirements.lock`, which your pip
  mirror must carry.
- **Setting**, optional: `REPOS_DIR` ("backend\.env"). Without it, registering a repository by its git URL asks
  for the target folder each time.
