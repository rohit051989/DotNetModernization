"""Repositories registered by their git URL (docs/VDI-SETUP.md section K): cloning them, and bringing a clone up to
date before a rescan. repository-ingest calls this, so a clone's progress and errors show in the repository's job.

git runs as the person, with their own credentials: Git Credential Manager or their SSH keys. The platform never
asks for, stores or logs a credential, and the URL itself never carries one (validate_clone_url refuses it). Every
prompt is switched off, so a clone that needs a sign-in fails at once, with how to sign in once outside the
platform, instead of waiting for an answer nobody can give.
"""
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Callable

from app.steps.repository_ingest import normalize_clone_url, run_git

# A transfer slower than 1 KB/s for a minute is abandoned rather than left hanging.
LOW_SPEED_LIMIT, LOW_SPEED_TIME = "1000", "60"
PROGRESS_EVERY_SECONDS = 2.0

_SIGN_IN_SIGNS = (
    "terminal prompts disabled", "could not read username", "could not read password", "authentication failed",
    "cannot prompt because user interactivity has been disabled", "permission denied (publickey",
    "host key verification failed", "invalid username or password", "http basic: access denied",
    "the requested url returned error: 401", "the requested url returned error: 403", "access denied",
    "repository not found",
)


class GitSourceError(Exception):
    """A clone or an update that did not happen, with what the person can do about it."""


def git_environment() -> dict[str, str]:
    """This process's environment with every git and SSH prompt switched off. Git Credential Manager and the SSH
    agent still answer from what the person has already stored; nothing can ask them anything."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env["GIT_HTTP_LOW_SPEED_LIMIT"] = LOW_SPEED_LIMIT
    env["GIT_HTTP_LOW_SPEED_TIME"] = LOW_SPEED_TIME
    for name in ("GIT_ASKPASS", "SSH_ASKPASS"):
        env.pop(name, None)
    env["SSH_ASKPASS_REQUIRE"] = "never"
    # SSH: no passphrase or host-key question. A person's own ssh command (GIT_SSH_COMMAND, GIT_SSH or
    # core.sshCommand) is theirs and is left as it is.
    if not (env.get("GIT_SSH_COMMAND") or env.get("GIT_SSH") or _git_config("core.sshCommand")):
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=30"
    return env


def _git_config(key: str) -> str | None:
    try:
        done = subprocess.run(["git", "config", "--global", "--get", key], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() or None


def _git(args: list[str], cwd: Path | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=git_environment(), stdin=subprocess.DEVNULL)


def _last_lines(text: str, count: int = 4) -> str:
    lines = [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]
    return " | ".join(lines[-count:])


def sign_in_help(url: str) -> str:
    if url.startswith("https://"):
        return (f"Sign in once, outside the platform, in your own PowerShell window: git ls-remote {url} . Git "
                "Credential Manager asks you to sign in and remembers it for your account. Then register again (or "
                "Rescan). The platform never asks for or stores a credential.")
    if url.startswith("file:"):
        return "Check that your account can read that folder."
    return (f"Check your SSH key once, outside the platform, in your own PowerShell window: git ls-remote {url} . "
            "Accept the host's key if asked, and load a key with a passphrase into the ssh-agent. Then register "
            "again (or Rescan). The platform never asks for or stores a credential.")


def failure_message(action: str, url: str, output: str) -> str:
    said = _last_lines(output) or "no message"
    if any(sign in output.lower() for sign in _SIGN_IN_SIGNS):
        return f"{action} {url} needs a sign-in the platform cannot give (git said: {said}). {sign_in_help(url)}"
    return f"{action} {url} failed (git said: {said})"


# ---------- The target folder ----------


def origin_of(folder: Path) -> str | None:
    return run_git(folder, "config", "--get", "remote.origin.url") if (folder / ".git").exists() else None


def is_clone_of(folder: Path, url: str) -> bool:
    origin = origin_of(folder)
    return origin is not None and normalize_clone_url(origin) == normalize_clone_url(url)


def target_state(folder: Path, url: str) -> tuple[str, str | None]:
    """What registering `url` into `folder` would do: ("clone", None) into a folder that does not exist or is
    empty; ("reuse", None) for an existing clone of the same URL, used as it is; or ("refuse", why)."""
    if not folder.exists():
        return "clone", None
    if not folder.is_dir():
        return "refuse", f"'{folder}' exists and is a file, not a folder."
    if not any(folder.iterdir()):
        return "clone", None
    if is_clone_of(folder, url):
        return "reuse", None
    origin = origin_of(folder)
    if origin:
        return "refuse", (f"'{folder}' is already a clone of another repository ({origin}). Choose another target "
                          "folder.")
    return "refuse", f"'{folder}' exists and is not empty. Choose an empty or new target folder."


# ---------- Clone and update ----------


def clone(url: str, branch: str | None, folder: Path, on_progress: Callable[[str], None] | None = None) -> None:
    """A full clone of `url` into `folder` (which does not exist or is empty), with core.longpaths=true. Reports git's
    progress lines to `on_progress` every PROGRESS_EVERY_SECONDS."""
    folder.parent.mkdir(parents=True, exist_ok=True)
    # The first core.longpaths applies to this clone's own checkout; the second is written into the clone's
    # configuration, for every later checkout, worktree and fetch in it.
    args =["git", "-c", "core.longpaths=true", "clone", "--progress", "-c", "core.longpaths=true"]
    if branch:
        args += ["--branch", branch]
    args += ["--", url, str(folder)]
    # Binary, read a byte at a time: git rewrites its progress line in place with \r, so lines end at \r or \n.
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               env=git_environment())
    output, line, last = [], bytearray(), 0.0
    assert process.stdout is not None
    while True:
        byte = process.stdout.read(1)
        if not byte:
            break
        if byte in (b"\r", b"\n"):
            text = line.decode("utf-8", errors="replace").strip()
            line = bytearray()
            if text:
                output.append(text)
                if on_progress and time.monotonic() - last >= PROGRESS_EVERY_SECONDS:
                    last = time.monotonic()
                    on_progress(text)
        else:
            line += byte
    if line:
        output.append(line.decode("utf-8", errors="replace").strip())
    process.stdout.close()
    if process.wait() != 0:
        raise GitSourceError(failure_message("Cloning", url, "\n".join(output[-20:])))


def update(folder: Path, url: str, branch: str) -> str:
    """Brings a clone the platform registered up to date before a rescan: fetches origin and fast-forwards `branch`.
    Refuses, changing nothing, when the clone has local changes, is on another branch, or has diverged. Returns
    what happened, in words."""
    if not is_clone_of(folder, url):
        raise GitSourceError(f"'{folder}' is no longer a clone of {url} (its origin is {origin_of(folder)}). Nothing "
                             "was fetched.")
    current = run_git(folder, "rev-parse", "--abbrev-ref", "HEAD")
    if current != branch:
        raise GitSourceError(f"The clone at '{folder}' is on {current or 'no branch'}, but this repository is "
                             f"registered on {branch}. Switch it back (git -C \"{folder}\" switch {branch}) and Rescan.")
    changed = _git(["status", "--porcelain", "--untracked-files=no"], cwd=folder, timeout=120)
    if changed.returncode != 0:
        raise GitSourceError(f"git status failed in '{folder}': {_last_lines(changed.stderr)}")
    if changed.stdout.strip():
        files = [line[3:] for line in changed.stdout.splitlines()[:5]]
        raise GitSourceError(f"The clone at '{folder}' has local changes ({', '.join(files)}"
                             f"{', ...' if len(changed.stdout.splitlines()) > 5 else ''}), so it was not updated. "
                             "Commit, stash or discard them outside the platform, then Rescan.")
    before = run_git(folder, "rev-parse", "HEAD")
    fetched = _git(["-c", "core.longpaths=true", "fetch", "--prune", "origin"], cwd=folder, timeout=3600)
    if fetched.returncode != 0:
        raise GitSourceError(failure_message("Fetching", url, fetched.stderr))
    upstream = f"refs/remotes/origin/{branch}"
    if run_git(folder, "rev-parse", "--verify", "--quiet", upstream) is None:
        raise GitSourceError(f"{url} has no branch {branch} any more. Nothing was changed.")
    merged = _git(["merge", "--ff-only", upstream], cwd=folder, timeout=600)
    if merged.returncode != 0:
        raise GitSourceError(f"{branch} in '{folder}' cannot be fast-forwarded to origin/{branch}: it has commits "
                             f"origin does not ({_last_lines(merged.stderr or merged.stdout, 2)}). Nothing was "
                             "changed; resolve it outside the platform, then Rescan.")
    after = run_git(folder, "rev-parse", "HEAD")
    if before == after:
        return f"fetched {url}: {branch} already up to date at {(after or '')[:8]}"
    return f"fetched {url}: {branch} fast-forwarded {(before or '')[:8]} -> {(after or '')[:8]}"
