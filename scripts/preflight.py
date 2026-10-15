"""Preflight: is this machine ready for the platform? (docs/VDI-SETUP.md section G.)

    python scripts\\preflight.py               every check; the database ones once the virtual environment exists
    python scripts\\preflight.py --database    the database checks only (bootstrap runs this after installing)
    python scripts\\preflight.py --no-database everything but the database (bootstrap's first stage)

Reports, in plain language, each prerequisite as PRESENT or MISSING, and exits 1 when anything is missing:

- Python 3.11.0 to 3.14.x; Node.js 20.19.0 or a later 20.x, or 22.12.0 or later, with npm 7.0.0 or later; any
  .NET 10 SDK from 10.0.100 (steps/step-003-fingerprinting/global.json), and a .NET 10 runtime the step programs can
  find (DOTNET_ROOT for a per-user SDK); git 2.17.0 or later. Anything older is MISSING;
- whether Windows long-path support and git's core.longpaths are on (reported, never failed);
- the database: a connection with DB_USER and DB_PASSWORD, and the right to create the configured schema (or to
  create tables in it, when it exists already); never the right to create a database or a superuser;
- each configured package source reachable: PIP_INDEX_URL, NPM_REGISTRY and each of NUGET_SOURCES (the public
  defaults when unset);
- RUNS_DIR set, outside the repository, and writable.

Standard library only, so it runs before anything is installed. It reads backend/.env and the environment, and never
prints a username or a password.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_SOURCES = {"PIP_INDEX_URL": "https://pypi.org/simple/", "NPM_REGISTRY": "https://registry.npmjs.org/",
                   "NUGET_SOURCES": "https://api.nuget.org/v3/index.json"}
results: list[tuple[bool, str, str]] = []

# The required versions (docs/VDI-SETUP.md section A). Python: the code is 3.11 syntax, the suite passes on
# 3.13 and 3.14, and every pinned dependency installs from a wheel up to 3.14 (backend/requirements.txt). Node.js:
# Vite's own requirement. npm: the lockfile is version 3. git: `git worktree remove`, the newest command the platform
# runs, is in 2.17. The .NET SDK: steps/step-003-fingerprinting/global.json.
MIN_PYTHON, MAX_PYTHON_EXCLUSIVE = (3, 11, 0), (3, 15, 0)
PYTHON_REQUIRED = "3.11.0 to 3.14.x needed"
NODE_REQUIRED = "20.19.0 or a later 20.x, or 22.12.0 or later, needed"
MIN_NPM, NPM_REQUIRED = (7, 0, 0), "7.0.0 or later needed"
MIN_GIT, GIT_REQUIRED = (2, 17, 0), "2.17.0 or later needed"
MAX_PATH = 259  # Windows' MAX_PATH, 260, less the terminating NUL: the longest full path git writes without core.longpaths


def check(ok: bool, what: str, detail: str) -> bool:
    results.append((ok, what, detail))
    print(f"  {'PRESENT' if ok else 'MISSING'}  {what}: {detail}", flush=True)
    return ok


def configuration() -> dict[str, str]:
    """backend/.env, then the environment over it."""
    values = {}
    env = BACKEND / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if m and not line.lstrip().startswith("#"):
                values[m.group(1).upper()] = m.group(2).strip().strip('"').strip("'")
    for key, value in os.environ.items():
        values[key.upper()] = value
    return values


def run(*args: str) -> tuple[int, str]:
    try:
        done = subprocess.run(list(args), capture_output=True, text=True, timeout=60)
        return done.returncode, (done.stdout + done.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return -1, str(error)


def version(text: str) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    return tuple(int(x) for x in m.groups() if x is not None) if m else ()


def node_fits(v: tuple[int, ...]) -> bool:
    """Vite's requirement: ^20.19.0 || >=22.12.0."""
    return (v[:1] == (20,) and v >= (20, 19, 0)) or v >= (22, 12, 0)


def sdk_fits(installed: str, pinned: str, roll_forward: str) -> bool:
    """global.json's rule. latestFeature: the same major.minor (.NET 10), at or above the pinned version, any feature
    band. latestPatch: the same feature band (10.0.3xx), at or above the pinned patch."""
    if version(installed)[:2] != version(pinned)[:2] or version(installed) < version(pinned) or "-" in installed:
        return False
    return roll_forward != "latestPatch" or installed.split(".")[2][:1] == pinned.split(".")[2][:1]


def sdk_required(pinned: str, roll_forward: str) -> str:
    major_minor = pinned.rsplit(".", 1)[0]
    if roll_forward == "latestPatch":
        return f"{pinned} or a later {major_minor}.{pinned.split('.')[2][0]}xx patch needed"
    return f"any .NET {major_minor.split('.')[0]} SDK from {pinned} needed"


def dotnet_runtime(pinned: str) -> None:
    """The step programs are framework-dependent .exe files: they find the .NET runtime through DOTNET_ROOT, else the
    machine-wide C:\\Program Files\\dotnet. A per-user SDK (dotnet-install) is found only through DOTNET_ROOT."""
    found = shutil.which("dotnet")
    if not found:
        return
    folder = Path(found).resolve().parent
    machine = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "dotnet"
    root = os.environ.get("DOTNET_ROOT", "")
    major = pinned.split(".")[0]
    runtimes = sorted(p.name for p in (folder / "shared" / "Microsoft.NETCore.App").glob(f"{major}.*")) \
        if (folder / "shared" / "Microsoft.NETCore.App").is_dir() else []
    if folder == machine.resolve():
        check(bool(runtimes), ".NET runtime for the step programs",
              f"{', '.join(runtimes) or 'none'} in {folder} (machine-wide; .NET {major} needed)")
    elif root and Path(root).resolve() == folder:
        check(bool(runtimes), ".NET runtime for the step programs",
              f"{', '.join(runtimes) or 'none'} in {folder}, which DOTNET_ROOT names (per-user; .NET {major} needed)")
    else:
        check(False, ".NET runtime for the step programs",
              f"dotnet comes from {folder}, but DOTNET_ROOT is {'not set' if not root else root}: the step programs "
              f"would not find this runtime. Set DOTNET_ROOT to {folder} for this account")


def tools() -> None:
    print("Tools")
    py = sys.version_info[:3]
    check(MIN_PYTHON <= py < MAX_PYTHON_EXCLUSIVE, "Python",
          f"{sys.version.split()[0]} ({PYTHON_REQUIRED}){'' if py >= MIN_PYTHON else ': too old'}"
          f"{': too new, the pinned dependencies have no build for it' if py >= MAX_PYTHON_EXCLUSIVE else ''}")
    code, out = run("node", "--version")
    v = version(out) if code == 0 else ()
    check(bool(v) and node_fits(v), "Node.js",
          f"{out if code == 0 else 'not found'} ({NODE_REQUIRED}){': too old' if v and not node_fits(v) else ''}")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    code, out = run(npm, "--version") if npm else (-1, "")
    v = version(out) if code == 0 else ()
    check(bool(v) and v >= MIN_NPM, "npm", f"{out if code == 0 else 'not found'} ({NPM_REQUIRED}){': too old' if v and v < MIN_NPM else ''}")
    sdk = json.loads((ROOT / "steps" / "step-003-fingerprinting" / "global.json").read_text(encoding="utf-8"))["sdk"]
    code, out = run("dotnet", "--list-sdks")
    sdks = [line.split()[0] for line in out.splitlines() if line.strip() and line[0].isdigit()] if code == 0 else []
    fits = [s for s in sdks if sdk_fits(s, sdk["version"], sdk.get("rollForward", "latestPatch"))]
    check(bool(fits), ".NET SDK", f"{', '.join(fits) if fits else 'none of ' + (', '.join(sdks) or 'none installed')} "
                                  f"({sdk_required(sdk['version'], sdk.get('rollForward', 'latestPatch'))}, "
                                  f"steps\\step-003-fingerprinting\\global.json)")
    dotnet_runtime(sdk["version"])
    code, out = run("git", "--version")
    v = version(out) if code == 0 else ()
    check(bool(v) and v >= MIN_GIT, "git", f"{out if code == 0 else 'not found'} ({GIT_REQUIRED}){': too old' if v and v < MIN_GIT else ''}")


def long_paths() -> None:
    """Reported, never failed: on, or off with what turning it on takes. Changing either is the machine owner's call
    (CLAUDE.md rule 14), so preflight only reads them."""
    print("Long paths (recommended on; reported only)")
    enabled = None
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
                enabled = winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
        except OSError:
            enabled = False
        note("Windows long-path support", "on" if enabled else
             "off: paths over 260 characters fail in some tools. An administrator turns it on with the group policy "
             "'Enable Win32 long paths' or LongPathsEnabled=1 under HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem")
    code, out = run("git", "config", "--get", "core.longpaths")
    on = code == 0 and out.strip().lower() in ("true", "1", "yes", "on")
    note("git core.longpaths", "on" if on else
         f"off: git cannot check out a file whose full path is over {MAX_PATH} characters. Turn it on with: "
         "git config --global core.longpaths true")
    code, out = run("git", "-C", str(ROOT), "ls-files")
    longest = max((len(line) for line in out.splitlines()), default=0) if code == 0 else 0
    total = len(str(ROOT)) + 1 + longest
    print(f"           Longest path in this checkout: {total} characters (this folder, {len(str(ROOT))}, plus its longest "
          f"file, {longest}). Without git core.longpaths, git cannot write a path over {MAX_PATH} characters, so an "
          f"install folder over {MAX_PATH - 1 - longest} characters fails. Keep the install folder and RUNS_DIR short.")


def note(what: str, detail: str) -> None:
    print(f"  {'ON     ' if detail == 'on' else 'OFF    '}  {what}: {detail}", flush=True)


def reachable(url: str) -> tuple[bool, str]:
    if not re.match(r"^https?://", url, re.I):
        path = Path(url)
        return path.is_dir(), f"folder {'exists' if path.is_dir() else 'does not exist'}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=15) as response:
            return response.status < 400, f"HTTP {response.status}"
    except urllib.error.HTTPError as error:
        return error.code < 500 and error.code not in (404,), f"HTTP {error.code}"
    except (urllib.error.URLError, OSError) as error:
        return False, f"unreachable ({getattr(error, 'reason', error)})"


def tool_sources(key: str) -> tuple[list[str], str]:
    """Where pip, npm or dotnet would install from when the .env key is empty: the tool's own configuration (pip.ini,
    .npmrc, the account's NuGet.Config, which is where a mirror that needs a login is usually set), else the public
    default."""
    if key == "PIP_INDEX_URL":
        code, out = run(sys.executable, "-m", "pip", "config", "get", "global.index-url")
        if code == 0 and out.strip().startswith("http"):
            return [out.strip()], "pip configuration"
    elif key == "NPM_REGISTRY":
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        code, out = run(npm, "config", "get", "registry") if npm else (-1, "")
        if code == 0 and out.strip().startswith("http"):
            return [out.strip()], "npm configuration"
    else:
        code, out = run("dotnet", "nuget", "list", "source", "--format", "short")
        enabled = [line.split(None, 1)[1].strip() for line in out.splitlines()
                   if code == 0 and line[:1] == "E" and len(line.split(None, 1)) == 2]
        if enabled:
            return enabled, "NuGet configuration"
    return [DEFAULT_SOURCES[key]], "default"


def sources(cfg: dict[str, str]) -> None:
    print("Package sources")
    for key in ("PIP_INDEX_URL", "NPM_REGISTRY", "NUGET_SOURCES"):
        configured = cfg.get(key, "").strip()
        urls, origin = ([u.strip() for u in configured.split(",") if u.strip()], "backend\\.env") if configured \
            else tool_sources(key)
        for url in urls:
            ok, detail = reachable(url)
            if ok and detail == "HTTP 401":
                detail += ": reachable; it needs a login, which the tool's own configuration must supply"
            check(ok, f"{key} {url} (from {origin})", detail)


def runs_dir(cfg: dict[str, str]) -> None:
    print("Run output")
    value = cfg.get("RUNS_DIR", "").strip()
    if not value:
        check(False, "RUNS_DIR", "not set (an absolute folder outside the repository)")
        return
    path = Path(value) if Path(value).is_absolute() else (BACKEND / value).resolve()
    if path.resolve().is_relative_to(ROOT.resolve()):
        check(False, "RUNS_DIR", f"{path} is inside the repository")
        return
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, delete=True):
            pass
        check(True, "RUNS_DIR", f"{path}, outside the repository, writable")
    except OSError as error:
        check(False, "RUNS_DIR", f"{path} is not writable ({error.strerror})")


def database(cfg: dict[str, str]) -> None:
    print("Database")
    try:
        import psycopg
    except ImportError:
        check(False, "database driver", "psycopg is not installed yet: bootstrap installs it, then runs these checks")
        return
    missing = [k for k in ("DB_NAME", "DB_USER", "DB_PASSWORD") if not cfg.get(k)]
    if missing:
        check(False, "database settings", f"{', '.join(missing)} not set")
        return
    secrets = [cfg["DB_USER"], cfg["DB_PASSWORD"]]

    def clean(text: str) -> str:
        for s in sorted(secrets, key=len, reverse=True):
            text = text.replace(s, "***")
        return text

    host, port, name = cfg.get("DB_HOST", "localhost"), cfg.get("DB_PORT", "5432"), cfg["DB_NAME"]
    schema = cfg.get("DB_SCHEMA", "public")
    try:
        with psycopg.connect(host=host, port=port, dbname=name, user=cfg["DB_USER"], password=cfg["DB_PASSWORD"],
                             connect_timeout=10) as c:
            server = c.execute("SHOW server_version").fetchone()[0]
            check(int(server.split(".")[0]) >= 17, "connection", f"{host}:{port}/{name}, PostgreSQL {server} (17 needed)")
            exists = c.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)).fetchone() is not None
            if exists:
                ok = c.execute("SELECT has_schema_privilege(%s, 'CREATE') AND has_schema_privilege(%s, 'USAGE')",
                               (schema, schema)).fetchone()[0]
                check(ok, f"schema {schema}", "exists; this login can create tables in it" if ok
                      else "exists, but this login cannot create tables in it")
            else:
                ok = c.execute("SELECT has_database_privilege(current_database(), 'CREATE')").fetchone()[0]
                check(ok, f"schema {schema}", "does not exist yet; this login can create it" if ok
                      else "does not exist, and this login cannot create a schema (needs CREATE on the database)")
            scratch = c.execute("SELECT has_database_privilege(current_database(), 'CREATE')").fetchone()[0]
            check(scratch, "scratch schemas", "this login can create and drop throwaway schemas for verification"
                  if scratch else "this login cannot create a schema: verification and the reproduce check need CREATE on the database")
            role = c.execute("SELECT rolsuper, rolcreatedb FROM pg_roles WHERE rolname = current_user").fetchone()
            print(f"           (superuser: {'yes' if role[0] else 'no'}, may create databases: {'yes' if role[1] else 'no'};"
                  " neither is needed)")
    except psycopg.Error as error:
        check(False, "connection", clean(str(error)).splitlines()[0])


def main() -> int:
    parser = argparse.ArgumentParser(prog="python scripts\\preflight.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--database", action="store_true", help="the database checks only")
    parser.add_argument("--no-database", action="store_true", help="everything but the database (bootstrap's first stage)")
    args = parser.parse_args()
    cfg = configuration()
    print(f"Preflight for {ROOT}")
    if not args.database:
        tools()
        sources(cfg)
        runs_dir(cfg)
        long_paths()
    if not args.no_database:
        database(cfg)
    missing = [what for ok, what, _ in results if not ok]
    print(f"\n{len(results) - len(missing)} present, {len(missing)} missing" + (f": {', '.join(missing)}" if missing else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
