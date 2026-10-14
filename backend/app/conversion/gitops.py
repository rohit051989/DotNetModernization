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


class CommitRefused(ValueError):
    pass


def platform_commit(worktree: Path, message: str, *, paths: list[str] | None = None, vocabulary: dict | None = None) -> str:
    """Every commit the platform makes in a client repository (36-COPILOT-ENHANCED-CONVERSION Part M). The message
    must be self-contained (no platform document, path, lifecycle step or vocabulary: app.engine.inputs.selfcontained)
    and carry no co-author trailer; otherwise nothing is committed. `paths`: what to stage, else everything."""
    from app.engine.inputs import selfcontained

    findings = selfcontained.check_commit_message(message, vocabulary)
    if findings:
        raise CommitRefused("commit message refused: " + "; ".join(f"{f['check']} ({f['match']})" for f in findings))
    git(worktree, "add", "--", *paths) if paths else git(worktree, "add", "--all")
    git(worktree, *PLATFORM_IDENTITY, "commit", "--no-verify", "-q", "-m", message)
    return head(worktree)


def commit(worktree: Path, message: str, vocabulary: dict | None = None) -> str:
    return platform_commit(worktree, message, vocabulary=vocabulary)


def expected_eols(worktree: Path, paths: list[str]) -> dict[str, str]:
    """The line ending git expects in the working tree for each path, from the repository's own settings: the `eol` and
    `text` attributes, then core.autocrlf, then core.eol. A file written so never shows as modified. "\n" outside a
    git repository."""
    if not paths or subprocess.run(["git", "-C", str(worktree), "rev-parse", "--is-inside-work-tree"],
                                   capture_output=True, text=True).returncode != 0:
        return {p: "\n" for p in paths}

    def config(key: str) -> str:
        return subprocess.run(["git", "-C", str(worktree), "config", "--get", key], capture_output=True, text=True).stdout.strip().lower()

    autocrlf, core_eol = config("core.autocrlf"), config("core.eol") or "native"
    native = "\r\n" if os.name == "nt" else "\n"
    attrs: dict[str, dict[str, str]] = {p: {} for p in paths}
    # Bytes, not text: on Windows a text pipe turns each "\n" into "\r\n", and every path would end in "\r".
    out = subprocess.run(["git", "-C", str(worktree), "check-attr", "--stdin", "text", "eol"],
                         input=("\n".join(paths) + "\n").encode("utf-8"), capture_output=True).stdout.decode("utf-8")
    for line in out.splitlines():
        path, _, rest = line.partition(": ")
        name, _, value = rest.partition(": ")
        if path in attrs:
            attrs[path][name] = value
    result = {}
    for p in paths:
        a = attrs[p]
        if a.get("eol") in ("lf", "crlf"):
            result[p] = "\r\n" if a["eol"] == "crlf" else "\n"
        elif a.get("text") == "unset":
            result[p] = "\n"                                   # binary or -text: no conversion
        elif autocrlf == "true":
            result[p] = "\r\n"
        elif autocrlf == "input":
            result[p] = "\n"
        elif a.get("text") in ("set", "auto"):
            result[p] = {"crlf": "\r\n", "lf": "\n"}.get(core_eol, native)
        else:
            result[p] = "\n"
    return result


def fast_forward(branch_worktree: Path, sha: str) -> None:
    git(branch_worktree, "merge", "--ff-only", sha)
