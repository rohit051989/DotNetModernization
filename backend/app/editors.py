"""Opening a file in the person's editor (04-FRONTEND-SPEC.md "File links").

The editors offered are those installed on the machine the platform runs on — the operator's own machine (CLAUDE.md
"Operating model"):
- VS Code, when `code` is on PATH. The browser opens it itself, through its vscode:// link, at the file and line.
- Visual Studio: every installation vswhere lists that is a real Visual Studio edition (Community, Professional or
  Enterprise) with the core editor, whose program is devenv.exe, from Visual Studio 2022 (version 17) on, with no
  upper bound. Other products the Visual Studio Installer lists — SQL Server Management Studio, which is built on
  the same shell, Build Tools, and anything else — are never offered, whatever their shell. Several installations
  are offered each by its full name, newest first. VISUAL_STUDIO_PATH names one devenv.exe in place of detection;
  VISUAL_STUDIO=off offers none. `python -m app.editors` reports what detection finds, opening nothing.

A browser cannot open a file in Visual Studio, so the backend does, in the person's own session: it hands the file to
an instance of the chosen installation that is running, through that installation's own versioned automation object
(DTE), and moves the caret to the line. The instance is found in the running object table by its versioned name
(`!VisualStudio.DTE.<major>.0:<process id>`) and accepted only when its program is the chosen devenv.exe; a
version-independent registration, which another product may own, is never used. With none running, it starts the
chosen devenv.exe (`devenv /Edit <file>`) and moves to the line once that instance is ready. When the line cannot be
set, the file is still open and the answer says so.

Nothing on the machine changes: no registry keys, no protocol handlers, no settings. Only a file inside a registered
repository, a conversion worktree or RUNS_DIR is opened; any other path is refused.
"""
import functools
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.workflow import processes

HELPER = Path(__file__).with_name("open_in_visual_studio.ps1")
VSWHERE = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"

# The Visual Studio editions; every other product id (SSMS, Build Tools, test agents, ...) is not Visual Studio.
EDITIONS = {
    "Microsoft.VisualStudio.Product.Community": "Community",
    "Microsoft.VisualStudio.Product.Professional": "Professional",
    "Microsoft.VisualStudio.Product.Enterprise": "Enterprise",
}
CORE_EDITOR = "Microsoft.VisualStudio.Component.CoreEditor"
OLDEST_MAJOR = 17          # Visual Studio 2022; every later version is accepted
OVERRIDE_ID = "path"       # the instance id of the installation VISUAL_STUDIO_PATH names


class PathNotAllowed(Exception):
    """The path is outside every folder the platform may open a file in, or is not a file."""


class EditorNotAvailable(Exception):
    """The editor is not installed on this machine."""


@dataclass(frozen=True)
class VisualStudio:
    devenv: str
    version: str            # installationVersion, e.g. 17.14.37
    name: str               # displayName, e.g. Visual Studio Enterprise 2026
    id: str = ""            # vswhere's instanceId; OVERRIDE_ID for VISUAL_STUDIO_PATH

    @property
    def major(self) -> int:
        return _version(self.version)[0]

    @property
    def prog_id(self) -> str:
        """This installation's own versioned automation object: VisualStudio.DTE.17.0 for 2022, .18.0 for 2026."""
        return f"VisualStudio.DTE.{self.major}.0"


@dataclass(frozen=True)
class Found:
    """One installation vswhere lists, and whether it is offered, with the reason when not."""
    name: str
    version: str
    path: str
    product: str
    accepted: bool
    reason: str
    id: str = ""


def _version(text: str) -> tuple[int, ...]:
    parts = []
    for part in (text or "").split("."):
        if not part.isdigit():
            break
        parts.append(int(part))
    return tuple(parts) or (0,)


def classify(entry: dict, with_core_editor: set[str]) -> Found:
    """Whether one vswhere entry is a Visual Studio to offer. `with_core_editor`: the instance ids vswhere lists with
    -requires Microsoft.VisualStudio.Component.CoreEditor."""
    product = entry.get("productId", "")
    path = entry.get("productPath", "")
    name = entry.get("displayName") or product or "unknown product"
    version = entry.get("installationVersion", "")
    instance = entry.get("instanceId", "")
    program = Path(path).name.lower() if path else ""
    reason = ""
    if product not in EDITIONS:
        if "managementstudio" in product.lower().replace(".", "") or "ssms" in (product + program).lower() \
                or "management studio" in name.lower():
            reason = "SQL Server Management Studio, not Visual Studio (it is built on the Visual Studio shell)"
        elif "buildtools" in product.lower():
            reason = "Build Tools: no editor"
        else:
            reason = f"{product or 'no product id'}: not a Visual Studio edition (Community, Professional or Enterprise)"
    elif instance not in with_core_editor:
        reason = "does not include the Visual Studio core editor"
    elif program != "devenv.exe":
        reason = f"its program is {program or 'not named'}, not devenv.exe"
    elif _version(version)[0] < OLDEST_MAJOR:
        reason = f"version {version}: older than Visual Studio 2022 (version {OLDEST_MAJOR})"
    elif entry.get("isComplete") is False or entry.get("isLaunchable") is False:
        reason = "the installation is incomplete: repair or finish it in the Visual Studio Installer"
    elif not Path(path).is_file():
        reason = f"{path} does not exist"
    return Found(name, version, path, product, not reason, reason, instance)


def _vswhere(*arguments: str) -> list[dict]:
    done = subprocess.run([str(VSWHERE), "-all", "-prerelease", "-products", "*", *arguments, "-format", "json", "-utf8"],
                          capture_output=True, text=True, encoding="utf-8", timeout=30)
    return json.loads(done.stdout or "[]")


def found_installations() -> list[Found]:
    """Every installation vswhere lists, Visual Studio or not, each with whether it is offered. Empty without vswhere."""
    if not VSWHERE.is_file():
        return []
    try:
        everything = _vswhere()
        core = {e.get("instanceId", "") for e in _vswhere("-requires", CORE_EDITOR)}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    return sorted((classify(entry, core) for entry in everything),
                  key=lambda f: (not f.accepted, tuple(-p for p in _version(f.version))))


def _from_path(path: str) -> tuple[VisualStudio | None, str]:
    """The installation VISUAL_STUDIO_PATH names, or None and why not. Its name and version come from vswhere when it
    lists that path, else from the file's own version."""
    target = Path(path)
    if target.name.lower() != "devenv.exe":
        return None, f"VISUAL_STUDIO_PATH {path} is not a devenv.exe"
    if not target.is_file():
        return None, f"VISUAL_STUDIO_PATH {path} does not exist"
    for found in found_installations():
        if found.path and Path(found.path).resolve() == target.resolve():
            return VisualStudio(str(target), found.version, found.name, OVERRIDE_ID), ""
    version = _file_version(target)
    return VisualStudio(str(target), version, f"Visual Studio {version.split('.')[0] or ''}".strip(), OVERRIDE_ID), ""


def _file_version(path: Path) -> str:
    done = processes.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                          f"(Get-Item -LiteralPath '{str(path).replace(chr(39), chr(39) * 2)}').VersionInfo.FileVersion"],
                         timeout=30)
    return (done.stdout or "").strip()


def installations() -> list[VisualStudio]:
    """The Visual Studio installations offered, newest first: VISUAL_STUDIO_PATH's alone when set, none with
    VISUAL_STUDIO=off. Read once per backend process."""
    return list(_installations())


@functools.lru_cache(maxsize=1)
def _installations() -> tuple[VisualStudio, ...]:
    if settings.visual_studio.strip().lower() == "off":
        return ()
    if settings.visual_studio_path.strip():
        vs, _ = _from_path(settings.visual_studio_path.strip())
        return (vs,) if vs else ()
    return tuple(VisualStudio(f.path, f.version, f.name, f.id) for f in found_installations() if f.accepted)


def visual_studio(installation: str | None = None) -> VisualStudio | None:
    """The installation with that id, or the newest; None when none is offered (or that id is not)."""
    offered = installations()
    if installation:
        return next((vs for vs in offered if vs.id == installation), None)
    return offered[0] if offered else None


def available() -> list[dict]:
    """The editors installed on this machine, as the UI offers them: VS Code, then each Visual Studio, newest first."""
    editors = []
    if shutil.which("code"):
        editors.append({"id": "vscode", "kind": "vscode", "label": "VS Code", "opens_at_line": True})
    for vs in installations():
        editors.append({"id": f"visual_studio:{vs.id}", "kind": "visual_studio", "label": vs.name,
                        "opens_at_line": True, "installation": vs.id, "version": vs.version})
    return editors


def report() -> str:
    """What detection finds, for `python -m app.editors`: opens nothing."""
    lines = [f"VS Code: {shutil.which('code') or 'not found (code is not on PATH)'}",
             f"VISUAL_STUDIO={settings.visual_studio or '(unset)'}  VISUAL_STUDIO_PATH={settings.visual_studio_path or '(unset)'}",
             f"vswhere: {VSWHERE}{'' if VSWHERE.is_file() else ' (not found: no Visual Studio Installer on this machine)'}"]
    found = found_installations()
    lines.append(f"Installations vswhere lists ({len(found)}):")
    for f in found:
        lines.append(f"  {'ACCEPTED' if f.accepted else 'REFUSED '}  {f.name}  {f.version}  {f.path or '(no program)'}"
                     + ("" if f.accepted else f"\n            why: {f.reason}"))
    if settings.visual_studio.strip().lower() == "off":
        lines.append("Offered in the UI: none (VISUAL_STUDIO=off)")
    else:
        if settings.visual_studio_path.strip():
            vs, why = _from_path(settings.visual_studio_path.strip())
            lines.append(f"VISUAL_STUDIO_PATH overrides detection: {why or f'{vs.name} {vs.version}'}")
        offered = installations()
        lines.append(f"Offered in the UI, newest first ({len(offered)}):" if offered else "Offered in the UI: none")
        lines += [f"  {vs.name}  {vs.version}  {vs.devenv}  (automation {vs.prog_id})" for vs in offered]
    return "\n".join(lines)


def allowed_roots(db: Session) -> list[Path]:
    """Where a file may be opened: every registered repository, every conversion worktree, and RUNS_DIR."""
    roots = [settings.runs_path]
    roots += [Path(r.local_path) for r in db.query(models.Repository).filter(models.Repository.deleted_at.is_(None))]
    # Each person's own clones on this machine (app.repositories.clones), of repositories not deleted: file links
    # open from them.
    from app.auth import machine

    roots += [Path(p) for (p,) in db.query(models.RepositoryClone.local_path)
              .join(models.Repository, models.Repository.id == models.RepositoryClone.repository_id)
              .filter(func.lower(models.RepositoryClone.hostname) == machine.hostname().lower(),
                      models.Repository.deleted_at.is_(None))]
    roots += [Path(p) for (p,) in db.query(models.ConversionPlan.worktree_path)]
    roots += [Path(p) for (p,) in db.query(models.EngineRun.worktree_path).filter(models.EngineRun.worktree_path.isnot(None))]
    return roots


def checked_file(db: Session, path: str) -> Path:
    """The file, with links and junctions followed, when it lies inside an allowed folder; else PathNotAllowed."""
    try:
        target = Path(path).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PathNotAllowed(f"{path} does not exist") from exc
    if not target.is_file():
        raise PathNotAllowed(f"{path} is not a file")
    for root in allowed_roots(db):
        try:
            if target.is_relative_to(root.resolve()):
                return target
        except OSError:
            continue
    raise PathNotAllowed(f"{path} is outside every registered repository, conversion worktree and RUNS_DIR: not opened")


def open_in_visual_studio(db: Session, path: str, line: int, installation: str | None = None) -> dict:
    """Opens the file at the line in the chosen Visual Studio (the newest when none is named).
    {"opened", "at_line", "message"}."""
    vs = visual_studio(installation)
    if vs is None:
        raise EditorNotAvailable("Visual Studio is not installed on this machine" if not installation
                                 else f"Visual Studio installation {installation} is not offered on this machine")
    target = checked_file(db, path)
    line = max(1, int(line))

    attached = _helper(vs, target, line, wait_seconds=0)
    if attached.get("state") == "not_running":
        # No instance to hand it to: start one, out of this process's tree, with no handles of ours, so it lives on.
        subprocess.Popen([vs.devenv, "/Edit", str(target)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        attached = _helper(vs, target, line, wait_seconds=90)
        if attached.get("state") != "at_line":
            return {"opened": True, "at_line": False,
                    "message": f"Opened {target.name} in a new {vs.name}. It could not be moved to line {line}: go there with Ctrl+G."}
    if attached.get("state") == "at_line":
        return {"opened": True, "at_line": True, "message": f"Opened {target.name} at line {line} in {vs.name}."}
    return {"opened": False, "at_line": False,
            "message": f"{vs.name} did not open {target.name}: {attached.get('reason') or 'no answer'}."}


def _helper(vs: VisualStudio, target: Path, line: int, wait_seconds: int) -> dict:
    """Runs the helper that talks to this installation's automation object; its one line of JSON."""
    done = processes.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(HELPER),
                          "-ProgId", vs.prog_id, "-Devenv", vs.devenv, "-Path", str(target), "-Line", str(line),
                          "-WaitSeconds", str(wait_seconds)],
                         timeout=wait_seconds + 60)
    for text in reversed(done.stdout.strip().splitlines()):
        try:
            return json.loads(text)
        except ValueError:
            continue
    return {"state": "failed", "reason": (done.stderr or done.stopped_why or "no answer").strip()[:300]}


if __name__ == "__main__":
    # python -m app.editors: what editor detection finds on this machine. Opens nothing.
    print(report())
    sys.exit(0)
