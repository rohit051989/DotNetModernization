"""Opening a file in the person's editor (04-FRONTEND-SPEC.md "File links").

The editors offered are those installed on the machine the platform runs on — the operator's own machine (CLAUDE.md
"Operating model"):
- VS Code, when `code` is on PATH. The browser opens it itself, through its vscode:// link, at the file and line.
- Visual Studio, when vswhere finds an installation. A browser cannot open a file in Visual Studio, so the backend
  does, in the person's own session: it hands the file to the Visual Studio instance that is running, through
  Visual Studio's automation object (DTE, the documented interface Visual Studio registers for itself while it runs),
  and moves the caret to the line. With none running, it starts one (`devenv /Edit <file>`) and moves to the line
  once that instance is ready. When the line cannot be set, the file is still open and the answer says so.

Nothing on the machine changes: no registry keys, no protocol handlers, no settings. Only a file inside a registered
repository, a conversion worktree or RUNS_DIR is opened; any other path is refused.
"""
import functools
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.workflow import processes

HELPER = Path(__file__).with_name("open_in_visual_studio.ps1")
VSWHERE = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"


class PathNotAllowed(Exception):
    """The path is outside every folder the platform may open a file in, or is not a file."""


class EditorNotAvailable(Exception):
    """The editor is not installed on this machine."""


@dataclass(frozen=True)
class VisualStudio:
    devenv: str
    version: str            # installationVersion, e.g. 17.14.37
    name: str               # displayName, e.g. Visual Studio Professional 2022

    @property
    def prog_id(self) -> str:
        """The automation object a running instance of this major version registers: VisualStudio.DTE.17.0."""
        return f"VisualStudio.DTE.{self.version.split('.')[0]}.0"


@functools.lru_cache(maxsize=1)
def visual_studio() -> VisualStudio | None:
    """The newest Visual Studio installed, from vswhere; None without one. Read once per backend process."""
    if not VSWHERE.is_file():
        return None
    try:
        done = subprocess.run([str(VSWHERE), "-latest", "-products", "*", "-format", "json", "-utf8"],
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        found = json.loads(done.stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if not found or not Path(found[0].get("productPath", "")).is_file():
        return None
    return VisualStudio(found[0]["productPath"], found[0].get("installationVersion", ""), found[0].get("displayName", "Visual Studio"))


def available() -> list[dict]:
    """The editors installed on this machine, as the UI offers them."""
    editors = []
    if shutil.which("code"):
        editors.append({"id": "vscode", "label": "VS Code", "opens_at_line": True})
    if vs := visual_studio():
        editors.append({"id": "visual_studio", "label": vs.name, "opens_at_line": True})
    return editors


def allowed_roots(db: Session) -> list[Path]:
    """Where a file may be opened: every registered repository, every conversion worktree, and RUNS_DIR."""
    roots = [settings.runs_path]
    roots += [Path(r.local_path) for r in db.query(models.Repository).filter(models.Repository.deleted_at.is_(None))]
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


def open_in_visual_studio(db: Session, path: str, line: int) -> dict:
    """Opens the file in Visual Studio at the line. {"opened", "at_line", "message"}."""
    vs = visual_studio()
    if vs is None:
        raise EditorNotAvailable("Visual Studio is not installed on this machine")
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
    """Runs the helper that talks to Visual Studio's automation object; its one line of JSON."""
    done = processes.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(HELPER),
                          "-ProgId", vs.prog_id, "-Path", str(target), "-Line", str(line), "-WaitSeconds", str(wait_seconds)],
                         timeout=wait_seconds + 60)
    for text in reversed(done.stdout.strip().splitlines()):
        try:
            return json.loads(text)
        except ValueError:
            continue
    return {"state": "failed", "reason": (done.stderr or done.stopped_why or "no answer").strip()[:300]}
