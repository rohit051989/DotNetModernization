"""Preflight: is this machine ready for the platform? (docs/VDI-SETUP.md: Preflight.)

    python scripts\\preflight.py               every check; the database ones once the virtual environment exists
    python scripts\\preflight.py --database    the database checks only (bootstrap runs this after installing)
    python scripts\\preflight.py --no-database everything but the database (bootstrap's first stage)

Reports, in plain language, each prerequisite as PRESENT or MISSING, and exits 1 when anything is missing:

- Python 3.11.0 to 3.14.x (the interpreter PYTHON names in backend/.env, else python on PATH: the one bootstrap
  uses); with DOTNET_ROOT set in backend/.env, that .NET first, as the backend applies it; Node.js 20.19.0 or a later 20.x, or 22.12.0 or later, with npm 7.0.0 or later; any
  .NET 10 SDK from 10.0.100 (steps/step-003-fingerprinting/global.json), and a .NET 10 runtime the step programs can
  find (DOTNET_ROOT for a per-user SDK); git 2.17.0 or later. Anything older is MISSING;
- whether Windows long-path support and git's core.longpaths are on (reported, never failed);
- the database: a connection with DB_USER and DB_PASSWORD, and the right to create the configured schema (or to
  create tables in it, when it exists already); never the right to create a database or a superuser;
- a final Python release, not an alpha, beta or release candidate; its exact patch release, with a warning when it
  is older than the one the suite passed on (backend/requirements.lock);
- each package source, tested with the tool bootstrap uses, so proxies, certificates and logins behave as in the real
  install: pip downloads a locked wheel, npm asks for the locked Vite, dotnet restores a package the step programs use.
  A failure shows the tool's own message. PIP_INDEX_URL, NPM_REGISTRY and NUGET_SOURCES, or, when empty, the tool's
  own configuration;
- the proxy settings it sees (HTTPS_PROXY, HTTP_PROXY, NO_PROXY, the tools' own) and, for each source, whether it
  goes through the proxy or direct (reported, never failed);
- where the platform runs: its own repository, or a subfolder of a host repository (a client's shared one), and the
  source commit it was copied from (PLATFORM_SOURCE.json); RUNS_DIR and REPOS_DIR outside the host repository
  (reported);
- RUNS_DIR set, outside the repository, and writable; REPOS_DIR, when set, absolute, outside the repository and
  RUNS_DIR, and writable;
- with the schema in place: whether a platform holds it (its heartbeat: live, or expired, and how to clear one known
  to be stale), and existing data a later rule would refuse, reported as WARNING and never changed (a checkout
  registered in two engagements before release 2).

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
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_SOURCES = {"PIP_INDEX_URL": "https://pypi.org/simple/", "NPM_REGISTRY": "https://registry.npmjs.org/",
                   "NUGET_SOURCES": "https://api.nuget.org/v3/index.json"}
results: list[tuple[bool, str, str]] = []

# The required versions (docs/VDI-SETUP.md: Before starting). Python: the code is 3.11 syntax, the suite passes on
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


warnings: list[tuple[str, str]] = []


def warn(what: str, detail: str) -> None:
    """Worth knowing, never a failure."""
    warnings.append((what, detail))
    print(f"  WARNING  {what}: {detail}", flush=True)


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
        done = subprocess.run(list(args), capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace")
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
              f"would not find this runtime. Set DOTNET_ROOT={folder} in backend\\.env")


def interpreter_of(cfg: dict[str, str]) -> str:
    """The Python bootstrap uses: PYTHON in backend/.env, else python on PATH."""
    return cfg.get("PYTHON", "").strip() or "python"


def tested_python() -> tuple[int, ...]:
    """The Python the full suite passed on, from backend/requirements.lock's header."""
    lock = BACKEND / "requirements.lock"
    m = re.search(r"(?m)^# tested-python: (\S+)", lock.read_text(encoding="utf-8")) if lock.exists() else None
    return version(m.group(1)) if m else ()


PRERELEASE = {"alpha": "alpha", "beta": "beta", "candidate": "release candidate"}


def python_check(cfg: dict[str, str]) -> None:
    """The interpreter bootstrap uses: a final release from 3.11 to 3.14, reported to the patch release."""
    named = cfg.get("PYTHON", "").strip()
    interpreter = interpreter_of(cfg)
    code, out = run(interpreter, "-c", "import sys; v = sys.version_info; print(f'{v.major}.{v.minor}.{v.micro}'); "
                                       "print(v.releaselevel, v.serial); print(sys.version.split()[0]); print(sys.executable)")
    lines = out.splitlines() if code == 0 else []
    py = version(lines[0]) if lines else ()
    level, serial = (lines[1].split() + ["", ""])[:2] if len(lines) > 1 else ("final", "0")
    full = lines[2] if len(lines) > 2 else (lines[0] if lines else "")
    where = f"{lines[3]}, " if len(lines) > 3 else ""
    origin = "PYTHON in backend\\.env" if named else "python on PATH"
    if py and level != "final":
        check(False, "Python",
              f"{full} ({where}{origin}) is a pre-release ({PRERELEASE.get(level, level)} {serial}). The platform needs a "
              f"final release: packages with compiled parts, such as pydantic-core, publish wheels for final releases, and a "
              f"pre-release's interpreter can still change under them, so the install fails or the backend breaks when it "
              f"starts (on 3.14.0b2, pydantic failed in bootstrap stage 7). Install the final {py[0]}.{py[1]}.x release "
              f"and name it as PYTHON in backend\\.env (docs/VDI-SETUP.md: Troubleshooting)")
        return
    ok = bool(py) and MIN_PYTHON <= py < MAX_PYTHON_EXCLUSIVE
    check(ok, "Python", f"{full if py else interpreter + ' not found'} ({where}{origin}; {PYTHON_REQUIRED})"
                        f"{': too old' if py and py < MIN_PYTHON else ''}"
                        f"{': too new, the pinned dependencies have no build for it' if py and py >= MAX_PYTHON_EXCLUSIVE else ''}")
    tested = tested_python()
    if ok and tested and py < tested:
        warn("Python", f"{full} is older than {'.'.join(map(str, tested))}, the release the full suite passed on "
                       "(backend\\requirements.lock). It is supported; the tested one, or a later patch, is safer")


def apply_dotnet_root(cfg: dict[str, str]) -> None:
    """DOTNET_ROOT in backend/.env, as the backend applies it (app.config.apply_dotnet_root): that folder first on
    PATH, and DOTNET_ROOT set, for the checks below and everything preflight starts."""
    root = cfg.get("DOTNET_ROOT", "").strip()
    if root:
        os.environ["DOTNET_ROOT"] = root
        os.environ["PATH"] = root + os.pathsep + os.environ.get("PATH", "")


def tools(cfg: dict[str, str] | None = None) -> None:
    print("Tools")
    python_check(cfg or {})
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
    # The SDK this dotnet uses (global.json's latestFeature picks the newest installed .NET 10 SDK the same way).
    code, used = run("dotnet", "--version") if fits else (-1, "")
    found = shutil.which("dotnet")
    used_text = f"{used.strip()} used, from {Path(found).parent}; " if code == 0 and used.strip() and found else ""
    check(bool(fits), ".NET SDK", f"{used_text}{'installed: ' + ', '.join(fits) if fits else 'none of ' + (', '.join(sdks) or 'none installed')} "
                                  f"({sdk_required(sdk['version'], sdk.get('rollForward', 'latestPatch'))}, "
                                  f"steps\\step-003-fingerprinting\\global.json)")
    dotnet_runtime(sdk["version"])
    code, out = run("git", "--version")
    v = version(out) if code == 0 else ()
    check(bool(v) and v >= MIN_GIT, "git", f"{out if code == 0 else 'not found'} ({GIT_REQUIRED}){': too old' if v and v < MIN_GIT else ''}")


def _git_top(path: Path) -> Path | None:
    code, out = run("git", "-C", str(path), "rev-parse", "--show-toplevel")
    return Path(out.splitlines()[-1]).resolve() if code == 0 and out else None


def platform_location(cfg: dict[str, str]) -> None:
    """Where the platform runs, and which of our commits it is. Reported, never failed."""
    print("Platform")
    top = _git_top(ROOT)
    source = None
    record = ROOT / "PLATFORM_SOURCE.json"
    if record.exists():
        try:
            source = json.loads(record.read_text(encoding="utf-8-sig"))
        except ValueError:
            source = None
    if top is None:
        note("location", f"{ROOT}, not in a git repository")
    elif top == ROOT.resolve() and source is not None:
        # The root of a client's repository dedicated to the platform: the whole repository is the platform.
        code, branch = run("git", "-C", str(top), "rev-parse", "--abbrev-ref", "HEAD")
        note("location", f"the root of the client's repository {top}, dedicated to the platform, on branch {branch.strip()}")
        for key in ("RUNS_DIR", "REPOS_DIR"):
            value = cfg.get(key, "").strip()
            if value and Path(value).is_absolute() and Path(value).resolve().is_relative_to(top):
                warn(key, f"{value} is inside the platform's repository {top}: everything written there shows as changes "
                          "in it. Put it outside, for example C:\\MP\\runs (docs/VDI-SETUP.md Part 1)")
    elif top == ROOT.resolve():
        # The commit, and a tag when one happens to point at it (installations follow master).
        code, head = run("git", "-C", str(ROOT), "rev-parse", "--short=12", "HEAD")
        code, tag = run("git", "-C", str(ROOT), "describe", "--tags", "--exact-match", "HEAD")
        note("location", f"{ROOT}, its own repository, at {head.strip()}{' (' + tag.strip() + ')' if code == 0 and tag.strip() else ''}")
    else:
        folder = ROOT.resolve().relative_to(top).as_posix()
        code, branch = run("git", "-C", str(top), "rev-parse", "--abbrev-ref", "HEAD")
        note("location", f"folder {folder} of the host repository {top}, on branch {branch.strip()}")
        if source is None:
            warn("platform source", "no PLATFORM_SOURCE.json in the platform folder: records cannot name our source "
                                    "commit. scripts\\update-platform.ps1 writes it (docs/VDI-SETUP.md Part 2)")
        for key in ("RUNS_DIR", "REPOS_DIR"):
            value = cfg.get(key, "").strip()
            if value and Path(value).is_absolute() and Path(value).resolve().is_relative_to(top):
                warn(key, f"{value} is inside the host repository {top}: everything written there shows as changes in "
                          "other people's repository. Put it outside, for example C:\\MP\\runs (docs/VDI-SETUP.md Part 1)")
    if source:
        note("platform source", f"{source.get('commit', '?')[:12]}"
                                f"{' (' + source['tag'] + ')' if source.get('tag') else ''}, copied {source.get('date', '?')}")


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
    label = "ON     " if detail == "on" else "OFF    " if detail.startswith("off") else "NOTE   "
    print(f"  {label}  {what}: {detail}", flush=True)


def masked(url: str) -> str:
    """A URL as it may be printed: no user or password."""
    return re.sub(r"(?<=://)[^/@\s]+@", "***@", url)


def tail(text: str, lines: int = 3) -> str:
    """The end of a tool's own message, credentials masked: what it said when it failed."""
    kept = [masked(l.strip()) for l in text.splitlines() if l.strip()][-lines:]
    return " | ".join(kept)[:500] or "no message"


def tool_sources(key: str, interpreter: str | None = None) -> tuple[list[str], str]:
    """Where pip, npm or dotnet would install from when the .env key is empty: the tool's own configuration (pip.ini,
    .npmrc, the account's NuGet.Config, which is where a mirror that needs a login is usually set), else the public
    default."""
    if key == "PIP_INDEX_URL":
        code, out = run(interpreter or sys.executable, "-m", "pip", "config", "get", "global.index-url")
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


PROXY_NAMES = ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY")


def proxy_settings() -> dict[str, str]:
    """HTTPS_PROXY, HTTP_PROXY and NO_PROXY as the tools see them (either case)."""
    return {n: os.environ.get(n) or os.environ.get(n.lower()) or "" for n in PROXY_NAMES}


def route(url: str, settings: dict[str, str]) -> str:
    """Whether a request to `url` goes through the proxy or direct, by HTTPS_PROXY / HTTP_PROXY and NO_PROXY."""
    if not re.match(r"^https?://", url, re.I):
        return "a folder: no network"
    host = urllib.parse.urlparse(url).hostname or ""
    proxy = settings["HTTPS_PROXY"] if url.lower().startswith("https") else settings["HTTP_PROXY"]
    if not proxy:
        return "direct (no proxy set)"
    for entry in [e.strip().lower() for e in settings["NO_PROXY"].split(",") if e.strip()]:
        if entry == "*" or host.lower() == entry.lstrip(".") or host.lower().endswith("." + entry.lstrip(".")):
            return f"direct (NO_PROXY {entry})"
    return f"through the proxy {masked(proxy)}"


def proxies(cfg: dict[str, str]) -> None:
    print("Proxy (reported only)")
    seen = proxy_settings()
    for name in PROXY_NAMES:
        print(f"           {name}: {masked(seen[name]) if seen[name] else 'not set'}")
    interpreter = interpreter_of(cfg)
    code, out = run(interpreter, "-m", "pip", "config", "get", "global.proxy")
    if code == 0 and out.strip():
        print(f"           pip's own proxy (pip configuration): {masked(out.strip())}")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    for key in ("https-proxy", "proxy"):
        code, out = run(npm, "config", "get", key) if npm else (-1, "")
        if code == 0 and out.strip() not in ("", "null", "undefined"):
            print(f"           npm's own {key} (npm configuration): {masked(out.strip())}")
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
                enabled = winreg.QueryValueEx(k, "ProxyEnable")[0] == 1
                server = winreg.QueryValueEx(k, "ProxyServer")[0] if enabled else ""
            if enabled:
                print(f"           Windows system proxy: {server} (dotnet uses it when HTTPS_PROXY is not set)")
        except OSError:
            pass


def _lock_versions() -> dict[str, str]:
    lock = BACKEND / "requirements.lock"
    pins = dict(re.findall(r"(?m)^([A-Za-z0-9_.-]+)==(\S+)$", lock.read_text(encoding="utf-8"))) if lock.exists() else {}
    return {k.lower(): v for k, v in pins.items()}


def _npm_version(name: str) -> str | None:
    lock = ROOT / "frontend" / "package-lock.json"
    try:
        return json.loads(lock.read_text(encoding="utf-8"))["packages"][f"node_modules/{name}"]["version"]
    except (OSError, KeyError, ValueError):
        return None


def pip_source(cfg: dict[str, str], index: str, origin: str, scratch: Path) -> None:
    """pip itself downloads one locked wheel from the index, as bootstrap stage 3 installs them."""
    interpreter = interpreter_of(cfg)
    package = f"pyyaml=={_lock_versions().get('pyyaml', '6.0.3')}"
    command = [interpreter, "-m", "pip", "download", "--no-deps", "--only-binary=:all:", "--no-cache-dir",
               "--disable-pip-version-check", "-q", "-d", str(scratch / "pip"), package]
    if cfg.get("PIP_INDEX_URL", "").strip():
        command += ["--index-url", index]
    code, out = run(*command)
    where = f"{masked(index)} (from {origin}; {route(index, proxy_settings())})"
    check(code == 0, "PIP_INDEX_URL", f"{where}: pip ({interpreter}) downloaded the {package} wheel" if code == 0
          else f"{where}: pip ({interpreter}) failed: {tail(out)}")


def npm_source(cfg: dict[str, str], registry: str, origin: str) -> None:
    """npm itself asks the registry for the locked Vite version, as bootstrap stage 5's npm ci does."""
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        check(False, "NPM_REGISTRY", f"{masked(registry)}: npm not found")
        return
    package = f"vite@{_npm_version('vite') or 'latest'}"
    command = [npm, "view", package, "version", "--prefer-online"]
    if cfg.get("NPM_REGISTRY", "").strip():
        command += ["--registry", registry]
    code, out = run(*command)
    where = f"{masked(registry)} (from {origin}; {route(registry, proxy_settings())})"
    check(code == 0, "NPM_REGISTRY", f"{where}: npm view {package} answered {out.strip().splitlines()[-1] if out.strip() else ''}"
          if code == 0 else f"{where}: npm failed: {tail(out)}")


PROBE_PACKAGE = ("Microsoft.Build.Locator", "1.11.2")    # small, and one the step programs restore


def nuget_source(cfg: dict[str, str], sources: list[str], label: str, scratch: Path, shown: list[str] | None = None) -> None:
    """dotnet itself restores one package the step programs use into an empty package folder (so it must come from
    the source, not a cache), with the sources bootstrap stage 6 uses."""
    project = scratch / f"nuget-probe-{len(list(scratch.glob('nuget-probe-*')))}"
    project.mkdir(parents=True)
    (project / "probe.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>'
        '<NuGetAudit>false</NuGetAudit></PropertyGroup><ItemGroup>'
        f'<PackageReference Include="{PROBE_PACKAGE[0]}" Version="{PROBE_PACKAGE[1]}" /></ItemGroup></Project>',
        encoding="utf-8")
    command = ["dotnet", "restore", str(project / "probe.csproj"), "--packages", str(project / "packages"),
               "--no-http-cache", "--force", "-nologo"]
    for s in sources:
        command += ["--source", s]
    code, out = run(*command)
    routes = "; ".join(sorted({route(s, proxy_settings()) for s in (sources or shown or [])}))
    check(code == 0, "NUGET_SOURCES", f"{label}; {routes}: dotnet restore got {PROBE_PACKAGE[0]} {PROBE_PACKAGE[1]}" if code == 0
          else f"{label}; {routes}: dotnet restore failed: {tail(out, 4)}")


def sources(cfg: dict[str, str]) -> None:
    print("Package sources (each tested with the tool bootstrap uses)")
    with tempfile.TemporaryDirectory(prefix="preflight-") as tmp:
        scratch = Path(tmp)
        interpreter = interpreter_of(cfg)
        configured = cfg.get("PIP_INDEX_URL", "").strip()
        urls, origin = ([configured], "backend\\.env") if configured else tool_sources("PIP_INDEX_URL", interpreter)
        pip_source(cfg, urls[0], origin, scratch)
        configured = cfg.get("NPM_REGISTRY", "").strip()
        urls, origin = ([configured], "backend\\.env") if configured else tool_sources("NPM_REGISTRY")
        npm_source(cfg, urls[0], origin)
        configured = [u.strip() for u in cfg.get("NUGET_SOURCES", "").split(",") if u.strip()]
        if configured:
            for s in configured:
                nuget_source(cfg, [s], f"{masked(s)} (from backend\\.env)", scratch)
        else:
            urls, origin = tool_sources("NUGET_SOURCES")
            nuget_source(cfg, [], f"{', '.join(masked(u) for u in urls)} (from {origin})", scratch, shown=urls)


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
    repos_dir(cfg, path)


def repos_dir(cfg: dict[str, str], runs: Path) -> None:
    """REPOS_DIR is optional: unset, the registration form asks where to clone."""
    value = cfg.get("REPOS_DIR", "").strip()
    if not value:
        note("REPOS_DIR", "not set (optional): registering by git URL asks for the target folder")
        return
    path = Path(value)
    if not path.is_absolute():
        check(False, "REPOS_DIR", f"{value} is not an absolute path")
    elif path.resolve().is_relative_to(ROOT.resolve()):
        check(False, "REPOS_DIR", f"{path} is inside the platform's folder: clone client repositories outside it")
    elif path.resolve().is_relative_to(runs.resolve()):
        check(False, "REPOS_DIR", f"{path} is inside RUNS_DIR: keep the clones apart from the run output")
    else:
        try:
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path, delete=True):
                pass
            check(True, "REPOS_DIR", f"{path}, outside the platform and RUNS_DIR, writable: repositories registered "
                                     "by URL are cloned under it")
        except OSError as error:
            check(False, "REPOS_DIR", f"{path} is not writable ({error.strerror})")


def database(cfg: dict[str, str]) -> None:
    print("Database")
    try:
        import psycopg
    except ImportError:
        venv_python = BACKEND / ".venv" / "Scripts" / "python.exe"
        if venv_python.exists() and Path(sys.executable).resolve() != venv_python.resolve():
            # Installed already: the driver is in backend/.venv. Run these checks there and take its findings.
            code, out = run(str(venv_python), str(Path(__file__).resolve()), "--database")
            for line in out.splitlines():
                m = re.match(r"^  (PRESENT|MISSING|WARNING)  ([^:]+): (.*)$", line)
                if m and m.group(1) == "WARNING":
                    warn(m.group(2), m.group(3))
                elif m:
                    check(m.group(1) == "PRESENT", m.group(2), m.group(3))
                elif line.startswith("  NOTE"):
                    print(line)
                elif line.startswith("           "):
                    print(line)
            return
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
            if exists:
                platform_state(c, schema)
    except psycopg.Error as error:
        check(False, "connection", clean(str(error)).splitlines()[0])


HEARTBEAT_STALE_SECONDS = 90   # app.heartbeat.STALE
CLEAR = r"cd backend; .venv\Scripts\python.exe -m app.heartbeat clear"


def _table(c, schema: str, table: str) -> bool:
    return c.execute("SELECT to_regclass(%s) IS NOT NULL", (f'"{schema}".{table}',)).fetchone()[0]


def platform_state(c, schema: str) -> None:
    """Who holds the schema, and existing data a later rule would refuse. Reported, never failed or changed."""
    if _table(c, schema, "platform_heartbeat"):
        row = c.execute(f'SELECT os_user, host, pid, platform_root, api_port, EXTRACT(EPOCH FROM now() - beat_at) '
                        f'FROM "{schema}".platform_heartbeat WHERE id = 1').fetchone()
        if row is None:
            note("platform", "no platform holds this schema now")
        else:
            user, host, pid, root, port, age = row
            age = int(age)
            if age > HEARTBEAT_STALE_SECONDS:
                note("platform", f"the last platform here ({user} on {host}, process {pid}) stopped without shutting "
                                 f"down {age} s ago; its heartbeat has expired, so the next start takes the schema over")
            else:
                warn("platform", f"a platform holds this schema: {user} on {host}, process {pid}, {root}, port {port}, "
                                 f"last heartbeat {age} s ago. A second one will not start on it. If you know that "
                                 f"platform has stopped (its VDI session closed, its machine restarted), its heartbeat "
                                 f"expires {HEARTBEAT_STALE_SECONDS} s after its last beat, or clear it now: {CLEAR}")
    if _table(c, schema, "repositories"):
        groups: dict[str, list[tuple[str, str, str]]] = {}
        for engagement, slug, path, normalised in c.execute(
                f'SELECT engagement_id, slug, local_path, local_path_normalised FROM "{schema}".repositories '
                'WHERE deleted_at IS NULL ORDER BY engagement_id, slug'):
            key = normalised.lower()
            if Path(path, ".git").exists():
                code, common = run("git", "-C", path, "rev-parse", "--git-common-dir")
                if code == 0 and common:
                    key = str((Path(path) / common.splitlines()[-1]).resolve()).lower()
            groups.setdefault(key, []).append((engagement, slug, path))
        for group in groups.values():
            if len({g[0] for g in group}) > 1:
                warn("existing data", f"one checkout is registered in several engagements ("
                                      f"{', '.join(f'{e}/{s}' for e, s, _ in group)}, {group[0][2]}), from before "
                                      "release 2 refused it. Left working and unchanged; see docs/VDI-SETUP.md "
                                      "More than one person")


def main() -> int:
    parser = argparse.ArgumentParser(prog="python scripts\\preflight.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--database", action="store_true", help="the database checks only")
    parser.add_argument("--no-database", action="store_true", help="everything but the database (bootstrap's first stage)")
    args = parser.parse_args()
    cfg = configuration()
    apply_dotnet_root(cfg)
    print(f"Preflight for {ROOT}")
    if not args.database:
        tools(cfg)
        proxies(cfg)
        sources(cfg)
        platform_location(cfg)
        runs_dir(cfg)
        long_paths()
    if not args.no_database:
        database(cfg)
    missing = [what for ok, what, _ in results if not ok]
    print(f"\n{len(results) - len(missing)} present, {len(missing)} missing" + (f": {', '.join(missing)}" if missing else "")
          + (f"; {len(warnings)} warning(s)" if warnings else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
