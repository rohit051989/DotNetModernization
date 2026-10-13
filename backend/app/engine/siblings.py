"""Sibling folders a repository reaches by relative path, for worktrees placed elsewhere.

A repository's nuget.config can name a feed beside it ("../EnterprisePackages/feed"). A worktree of it under
runs/ has no such sibling, so restore fails as soon as it needs a package that is not already in the global
NuGet cache. For each name an experiment configures (`sibling_links`), a directory junction is made beside the
worktree pointing at the folder beside the registered checkout. A junction is a link: removing it with
`remove` never touches what it points at. Nothing is written inside the worktree, so the diff is unaffected.
"""
import os
import subprocess
from pathlib import Path


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
