"""Sibling folders a repository reaches by relative path, for worktrees placed elsewhere.

A repository's nuget.config can name a feed beside it ("../EnterprisePackages/feed"). A worktree of it under
runs/ has no such sibling, so restore fails as soon as it needs a package that is not already in the global
NuGet cache. For each name an experiment configures (`sibling_links`), a directory junction is made beside the
worktree pointing at the folder beside the registered checkout. A junction is a link: removing it with
`remove` never touches what it points at. Nothing is written inside the worktree, so the diff is unaffected.

`detect` finds the names a repository needs without being told: every package source in its nuget.config files that
is a relative path leading out of the repository into a folder beside it (36-COPILOT-ENHANCED-CONVERSION Part N: a
repository registered from the UI is prepared with no one naming its siblings).
"""
import os
import re
import subprocess
from pathlib import Path

NUGET_CONFIG = re.compile(r"(?i)^nuget\.config$")
SOURCE_VALUE = re.compile(r"""<add\s[^>]*\bvalue\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def detect(checkout: Path) -> list[str]:
    """The folders beside `checkout` that its nuget.config package sources reach by relative path."""
    root = checkout.resolve()
    names = set()
    listed = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True).stdout.splitlines()
    for rel in listed:
        if not NUGET_CONFIG.match(Path(rel).name):
            continue
        config = root / rel
        try:
            text = config.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        for value in SOURCE_VALUE.findall(text):
            if re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I) or Path(value).is_absolute() or not value.startswith(".."):
                continue
            target = (config.parent / value.replace("\\", "/")).resolve()
            if target.is_relative_to(root.parent) and not target.is_relative_to(root):
                name = target.relative_to(root.parent).parts[0]
                if (root.parent / name).is_dir():
                    names.add(name)
    return sorted(names)


def link(worktree: Path, checkout: Path, names: list[str]) -> list[Path]:
    made = []
    for name in names or []:
        target = (checkout.parent / name).resolve()
        if not target.is_dir():
            raise FileNotFoundError(f"{target} does not exist beside the registered checkout")
        junction = worktree.parent / name
        if os.path.lexists(junction):
            if os.path.isjunction(junction) and os.path.samefile(junction, target):
                continue
            raise FileExistsError(f"{junction} exists and is not a junction to {target}")
        subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)], check=True, capture_output=True)
        made.append(junction)
    return made


def remove(parent: Path, names: list[str]) -> None:
    """Removes the junctions only; what they point at is untouched."""
    for name in names or []:
        junction = parent / name
        if os.path.isjunction(junction):
            os.rmdir(junction)
