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

The platform repository is the one this file is in. Run output (RUNS_DIR) is gitignored, so it never makes the
tree dirty.
"""
import subprocess
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[3]


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(PLATFORM_ROOT), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def platform_state() -> dict:
    """{"commit": the platform's HEAD, "dirty": whether tracked or untracked (not ignored) files differ from it}."""
    return {"commit": _git("rev-parse", "HEAD").strip(), "dirty": bool(_git("status", "--porcelain").strip())}


def require_clean(expected: str | None = None) -> str:
    """The platform commit, when the tree is clean and (given `expected`) at that commit; else an error saying why."""
    state = platform_state()
    if state["dirty"]:
        raise RuntimeError("the platform has uncommitted changes (git status in the platform repository): commit them "
                           "first, so the experiment can name the commit it is measured with")
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
