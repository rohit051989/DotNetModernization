"""Git for the unit loop: the conversion branch's worktree, a scratch worktree
per unit, and fast-forwarding the branch to a unit's commit.

Nothing here touches the repository's checked-out working tree. Worktrees
live outside it, under the platform's runs directory; the branch is created
from the plan's legacy commit. Commits are made as the platform, with the
identity passed on the command line, so no git configuration is written.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

PLATFORM_IDENTITY = ["-c", "user.name=Modernization Platform", "-c", "user.email=platform@modernization.local",
                     "-c", "commit.gpgsign=false"]


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and done.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def ensure_branch_worktree(repo: Path, worktree: Path, branch: str, start: str) -> None:
    """The conversion branch, checked out in its own worktree."""
    if worktree.exists():
        return
    worktree.parent.mkdir(parents=True, exist_ok=True)
    exists = git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).strip()
    if exists:
        git(repo, "worktree", "add", str(worktree), branch)
    else:
        git(repo, "worktree", "add", "-b", branch, str(worktree), start)


def add_scratch(repo: Path, scratch: Path, commit: str) -> None:
    if scratch.exists():
        remove(repo, scratch)
    scratch.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "--detach", str(scratch), commit)


def _rmtree(path: Path) -> None:
    def clear_readonly(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if path.exists():
        shutil.rmtree(path, onerror=clear_readonly)


def remove(repo: Path, worktree: Path) -> None:
    """Discards a worktree: unregisters it, then deletes what is left."""
    git(repo, "worktree", "remove", "--force", str(worktree), check=False)
    _rmtree(worktree)
    git(repo, "worktree", "prune")


def changed_files(worktree: Path) -> list[str]:
    """Tracked and untracked changes, ignored files excluded (bin/, obj/)."""
    out = git(worktree, "status", "--porcelain=v1", "--untracked-files=all")
    return sorted(line[3:].strip().strip('"') for line in out.splitlines() if line.strip())


def diff(worktree: Path) -> str:
    git(worktree, "add", "--intent-to-add", "--all")
    return git(worktree, "diff", "--binary")


def commit(worktree: Path, message: str) -> str:
    git(worktree, "add", "--all")
    git(worktree, *PLATFORM_IDENTITY, "commit", "--no-verify", "-m", message)
    return head(worktree)


def fast_forward(branch_worktree: Path, sha: str) -> None:
    git(branch_worktree, "merge", "--ff-only", sha)
