"""Preflight: is this machine ready for the platform? (01-ENVIRONMENT-SETUP.md section 10.)

    python scripts\\preflight.py               every check; the database ones once the virtual environment exists
    python scripts\\preflight.py --database    the database checks only (bootstrap runs this after installing)
    python scripts\\preflight.py --no-database everything but the database (bootstrap's first stage)

Reports, in plain language, each prerequisite as PRESENT or MISSING, and exits 1 when anything is missing:

- Python 3.11 or later, Node.js 18 or later with npm, the .NET SDK the step programs pin, git;
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


def tools() -> None:
    print("Tools")
    check(sys.version_info >= (3, 11), "Python", f"{sys.version.split()[0]} (3.11 or later needed)")
    code, out = run("node", "--version")
    check(code == 0 and version(out) >= (18,), "Node.js", f"{out or 'not found'} (18 or later needed)")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    code, out = run(npm, "--version") if npm else (-1, "")
    check(code == 0, "npm", out or "not found")
    pinned = json.loads((ROOT / "steps" / "step-003-fingerprinting" / "global.json").read_text(encoding="utf-8"))["sdk"]["version"]
    code, out = run("dotnet", "--list-sdks")
    sdks = [line.split()[0] for line in out.splitlines() if line.strip() and line[0].isdigit()] if code == 0 else []
    fits = [s for s in sdks if version(s)[:2] == version(pinned)[:2] and s.split(".")[2][:1] == pinned.split(".")[2][:1]
            and version(s) >= version(pinned)]
    check(bool(fits), ".NET SDK", f"{', '.join(fits) if fits else 'none'} (the step programs pin {pinned}, latest patch)")
    code, out = run("git", "--version")
    check(code == 0, "git", out or "not found")


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


def sources(cfg: dict[str, str]) -> None:
    print("Package sources")
    for key in ("PIP_INDEX_URL", "NPM_REGISTRY", "NUGET_SOURCES"):
        configured = cfg.get(key, "").strip()
        for url in [u.strip() for u in (configured or DEFAULT_SOURCES[key]).split(",") if u.strip()]:
            ok, detail = reachable(url)
            check(ok, f"{key} {url}{'' if configured else ' (default)'}", detail)


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
    if not args.no_database:
        database(cfg)
    missing = [what for ok, what, _ in results if not ok]
    print(f"\n{len(results) - len(missing)} present, {len(missing)} missing" + (f": {', '.join(missing)}" if missing else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
