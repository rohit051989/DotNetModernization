"""The instrument: which platform commit an experiment was prepared at, and each verification ran at
(36-COPILOT-ENHANCED-CONVERSION Part J, "Pinned instrument").

An experiment compares engine runs measured by the platform. If the platform changes between runs (a new catalog
item, a different verifier rule, a fixed detector), two runs are no longer measured by the same instrument. So:

- `create` records the platform commit in experiment.yaml (`platform_commit`), and refuses while the platform's
  working tree has uncommitted changes: an uncommitted state cannot be named, so it cannot be pinned;
- `prepare` refuses unless the platform is clean and at that commit;
- every verification records the commit it ran at, and whether the tree was clean (`platform` in
  verification.json);
- `report` and `calibrate` flag any verification made at another commit, or from a changed tree.

Where the platform's identity comes from (docs/VDI-SETUP.md, "Part 1"):
- the platform folder is its own git repository (our development checkout, or an install made from a release
  bundle): its HEAD, and `git status` of that repository;
- the platform folder is a subfolder of someone else's repository (a client keeps the platform in a folder of a
  shared repository, without our .git): the commit of OUR source it was copied from, read from PLATFORM_SOURCE.json
  (written by scripts/update-platform.ps1), and `git status` limited to the platform folder, run from the host
  repository's real root. The host repository's own commit and branch are recorded beside it, so every record
  traces back both to our release and to the client's commit that carried it.
Run output (RUNS_DIR) lives outside the platform folder, so it never makes the tree dirty.
"""
import json
import subprocess
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[3]
SOURCE_FILE = "PLATFORM_SOURCE.json"


def _git(root: Path, *args: str, check: bool = True) -> str | None:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if done.returncode != 0:
        if check:
            raise subprocess.CalledProcessError(done.returncode, done.args, done.stdout, done.stderr)
        return None
    return done.stdout


def source_record(root: Path = PLATFORM_ROOT) -> dict | None:
    """PLATFORM_SOURCE.json: {commit, tag, date, ...} of our source the platform folder was copied from, or None."""
    path = root / SOURCE_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def location(root: Path = PLATFORM_ROOT) -> dict:
    """{"kind": "repository" | "subfolder" | "no_git", "top": the repository's real root, "folder": the platform
    folder relative to it (posix; "" when it is the root)}."""
    top = (_git(root, "rev-parse", "--show-toplevel", check=False) or "").strip()
    if not top:
        return {"kind": "no_git", "top": None, "folder": None}
    top_path = Path(top).resolve()
    folder = root.resolve().relative_to(top_path).as_posix() if root.resolve() != top_path else ""
    return {"kind": "subfolder" if folder else "repository", "top": str(top_path), "folder": folder}


# A release tag: release-N (release 7 onward), or the older <prefix>-release-N of releases 1 to 6. Any other tag on the
# commit is not a release, and is not reported as one.
RELEASE_TAGS = ("--match", "release-*", "--match", "*-release-*")


def platform_state(root: Path = PLATFORM_ROOT) -> dict:
    """{"commit": our source commit the platform runs, "dirty": whether the platform's own files differ from what is
    committed, "source": {commit, tag, date} with where it was read from, "host": the host repository's commit and
    branch when the platform is a subfolder of one, else None}."""
    where = location(root)
    if where["kind"] == "repository":
        commit = _git(root, "rev-parse", "HEAD").strip()
        tag = (_git(root, "describe", "--tags", "--exact-match", *RELEASE_TAGS, "HEAD", check=False) or "").strip() or None
        dirty = bool(_git(root, "status", "--porcelain").strip())
        return {"commit": commit, "dirty": dirty, "source": {"commit": commit, "tag": tag, "from": "git"}, "host": None}
    record = source_record(root) or {}
    source = {"commit": record.get("commit"), "tag": record.get("tag"), "date": record.get("date"),
              "from": SOURCE_FILE if record else None}
    if where["kind"] == "no_git":
        return {"commit": record.get("commit"), "dirty": False, "source": source, "host": None}
    top = Path(where["top"])
    # From the repository's real root, and only the platform's folder: other people's changes elsewhere in the host
    # repository are theirs, and never make the platform dirty.
    dirty = bool(_git(top, "status", "--porcelain", "--", where["folder"]).strip())
    host = {"root": where["top"], "folder": where["folder"],
            "commit": (_git(top, "rev-parse", "HEAD", check=False) or "").strip() or None,
            "branch": (_git(top, "rev-parse", "--abbrev-ref", "HEAD", check=False) or "").strip() or None}
    return {"commit": record.get("commit"), "dirty": dirty, "source": source, "host": host}


def describe(state: dict | None) -> str:
    """One line: our source commit and tag, and the host repository's commit when the platform is a subfolder."""
    if not state or not state.get("commit"):
        if state and state.get("host"):
            return (f"platform source unknown: no {SOURCE_FILE} in {state['host']['folder']} (run "
                    f"scripts/update-platform.ps1); host repository at {(state['host']['commit'] or '?')[:12]}")
        return "platform commit not recorded"
    source = state.get("source") or {}
    said = f"platform {state['commit'][:12]}" + (f" ({source['tag']})" if source.get("tag") else "")
    if state.get("dirty"):
        said += " with uncommitted changes"
    host = state.get("host")
    if host:
        said += (f", in {host['folder']}/ of the host repository at {(host['commit'] or '?')[:12]}"
                 f" on {host['branch'] or '?'}")
    return said


def require_clean(expected: str | None = None) -> str:
    """The platform commit, when the tree is clean and (given `expected`) at that commit; else an error saying why."""
    state = platform_state()
    if state["dirty"]:
        raise RuntimeError("the platform has uncommitted changes (git status of the platform's folder): commit them "
                           "first, so the experiment can name the commit it is measured with")
    if not state["commit"]:
        raise RuntimeError(f"the platform's source commit is not known: no {SOURCE_FILE} in its folder "
                           "(scripts/update-platform.ps1 writes it)")
    if expected and not state["commit"].startswith(expected):
        raise RuntimeError(f"the platform is at {state['commit'][:12]}, not the experiment's platform_commit "
                           f"{expected[:12]}: check it out, or create a new generation at this commit")
    return state["commit"]


def mismatch(config: dict, verification: dict) -> str | None:
    """Why a verification was not made with the experiment's pinned platform and frozen package lookups, or None
    when it was."""
    frozen = (config.get("package_lookups") or {}).get("sha256")
    answered = verification.get("packageLookups") or {}
    if frozen and answered.get("sha256") != frozen:
        return (f"package lookups answered from {'live feeds' if answered.get('source') != 'snapshot' else answered['sha256'][:12]}"
                f", not the experiment's frozen snapshot {frozen[:12]}")
    pinned = config.get("platform_commit")
    state = verification.get("platform")
    if not pinned:
        return "experiment.yaml records no platform_commit"
    if not state:
        return "the verification records no platform commit (made before the instrument was pinned)"
    if state["commit"] != pinned:
        return f"verified at platform {state['commit'][:12]}, not the experiment's {pinned[:12]}"
    if state.get("dirty"):
        return f"verified at platform {pinned[:12]} with uncommitted changes"
    return None
