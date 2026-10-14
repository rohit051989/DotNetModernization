"""Package upgrades judged against what the conversion asked for (36-COPILOT-ENHANCED-CONVERSION Part N).

Re-discovery looks packages up live, so on the branch it suggests today's newest release. A conversion was asked for
the version its inputs named when it was prepared, and a release published since then is not its failure. So an
upgrade item's place is met when the package is at or above the version the inputs asked for. A newer release
since then is listed apart, as information, and is never a remaining work item.

The versions asked for are read from the platform's inputs commit on the branch, the commit made when the conversion
was prepared. That commit is the record. Vulnerabilities are not judged here: `package-vulnerable` is always judged
against today's advisories, because a new advisory is a real finding.
"""
import re
from pathlib import Path

from app.conversion import gitops
from app.engine import paths
from app.engine.inputs import render

# The items whose place is a version to reach: "Package current -> recommended".
UPGRADE_ITEMS = ("package-upgrade-safe", "package-upgrade-breaking")
UPGRADE_VALUE = re.compile(r"^(?P<package>\S+) (?P<current>\S+) -> (?P<newest>\S+)")
PLATFORM_EMAIL = next(a.split("=", 1)[1] for a in gitops.PLATFORM_IDENTITY if a.startswith("user.email="))


def version_key(version: str) -> tuple:
    """NuGet ordering: numeric parts, then a release above any of its prereleases."""
    core, _, pre = version.split("+")[0].partition("-")
    numbers = [int(x) if x.isdigit() else 0 for x in core.split(".")]
    numbers += [0] * (4 - len(numbers))
    labels = tuple((0, int(p), "") if p.isdigit() else (1, 0, p.lower()) for p in pre.split(".")) if pre else ()
    return tuple(numbers), 0 if pre else 1, labels


def inputs_commit(root: Path, base: str, tip: str) -> str | None:
    """The first commit after `base` made by the platform: the inputs, written when the conversion was prepared."""
    for line in gitops.git(root, "log", "--reverse", "--format=%H %ae", f"{base}..{tip}").splitlines():
        sha, _, email = line.partition(" ")
        if email.strip().lower() == PLATFORM_EMAIL:
            return sha
    return None


def asked_for(root: Path, commit: str) -> list[dict]:
    """[{project, package, current, asked, instruction}] from the package instructions in `commit`."""
    names = gitops.git(root, "ls-tree", "-r", "--name-only", commit, "--", paths.UPGRADE_SKILLS_DIR).splitlines()
    files = {n: gitops.git(root, "show", f"{commit}:{n}") for n in names if Path(n).name.startswith("applying-package-")}
    return render.package_targets(files)


def _target(targets: list[dict], project: str, package: str) -> str | None:
    """The version asked for this package in this project; else the highest asked for it in any project."""
    same = [t["asked"] for t in targets if t["package"].lower() == package.lower()]
    own = [t["asked"] for t in targets if t["package"].lower() == package.lower() and t["project"] == project]
    pool = own or same
    return max(pool, key=version_key) if pool else None


def judge(model: dict, targets: list[dict]) -> tuple[dict, list[dict]]:
    """(the model with every upgrade place that met its target removed, the releases since: [{project, package,
    version, asked, newest}]). Other items, package-vulnerable among them, are untouched."""
    items, since = [], []
    for item in model["items"]:
        if item["id"] not in UPGRADE_ITEMS:
            items.append(item)
            continue
        left = []
        for occ in item["occurrences"]:
            m = UPGRADE_VALUE.match(occ.get("value") or "")
            asked = _target(targets, occ["project"], m["package"]) if m else None
            if m and asked and version_key(m["current"]) >= version_key(asked):
                since.append({"project": occ["project"], "package": m["package"], "version": m["current"],
                              "asked": asked, "newest": m["newest"], "item": item["id"]})
            else:
                left.append(occ)
        if left:
            items.append({**item, "occurrences": left})
    return {**model, "items": items}, since
