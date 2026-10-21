"""Running a child process so that nothing can wait forever (release 5).

Every process a step starts, and every step that is itself a process, runs through `run`:

- both output pipes are read on their own threads, all the time, so a child that writes more than a pipe holds can
  never block on a pipe nobody reads;
- a time limit, and optionally a stall limit: when the child reports no new progress for that long, it is stopped as
  stalled, with the last phase and item it reported, instead of waiting for the full time limit;
- the whole process tree is ended — the child and everything it started (MSBuild worker nodes, a compiler server, a
  test host). On Windows the child is placed in a job object at start, and the job is terminated; `taskkill /T` covers
  anything that left the job. This also runs when a child exits normally, so nothing it started is left running;
- after the tree is ended, the reader threads are given a few seconds, never more: a grandchild that inherited a pipe
  can keep it open, and waiting for it to close is exactly how a caller hangs.

Progress is reported on stderr, one line at a time: ``##progress {"phase": ..., "done": n, "total": m, "item": ...}``
(app/workflow/progress.py; Fingerprinting.StepHost.StepProgress). A line repeated with nothing changed keeps the
child alive in the eyes of the time limit but not of the stall limit: a stall is no change in phase, count or item.
"""
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

PROGRESS_PREFIX = "##progress "
_READER_GRACE_SECONDS = 5
_EXIT_GRACE_SECONDS = 10


@dataclass
class Outcome:
    returncode: int | None
    stdout: str
    stderr: str
    seconds: float
    timed_out: bool = False
    stalled: bool = False
    last_progress: dict | None = None
    stopped_why: str | None = None
    progress_lines: int = 0
    killed: list[int] = field(default_factory=list)


def parse_progress(line: str) -> dict | None:
    """The progress a ``##progress {json}`` line reports, or None for any other line."""
    if not line.startswith(PROGRESS_PREFIX):
        return None
    try:
        value = json.loads(line[len(PROGRESS_PREFIX):])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _position(progress: dict | None) -> tuple:
    """What counts as moving on: phase, items done, and the current item."""
    if not progress:
        return ()
    return progress.get("phase"), progress.get("done"), progress.get("item")


# ---------------------------------------------------------------- the process tree

class _Job:
    """A Windows job object holding a process and everything it starts. Elsewhere, a no-op."""

    def __init__(self):
        self.handle = None
        self.holds = False              # whether the child is in the job (then ending the job ends its whole tree)
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._k32.CreateJobObjectW.restype = wintypes.HANDLE
        self.handle = self._k32.CreateJobObjectW(None, None)

        class LIMIT(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("Basic", LIMIT), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = EXTENDED()
        info.Basic.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: closing the job ends the tree
        self._k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info))

    def add(self, process: subprocess.Popen) -> None:
        if self.handle:
            self.holds = bool(self._k32.AssignProcessToJobObject(self.handle, int(process._handle)))

    def end(self) -> None:
        if self.handle:
            self._k32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self._k32.CloseHandle(self.handle)
            self.handle = None


def end_tree(process: subprocess.Popen, job: _Job | None = None, thorough: bool = True) -> None:
    """Ends `process` and everything it started. The job object covers the tree; `taskkill /T` is added when the child
    is not in a job, or, when `thorough`, for anything that may have left it — a stopped child, never one that exited
    by itself, so that a short command does not pay for a second process."""
    if job is not None:
        job.end()
    if os.name == "nt":
        if thorough or job is None or not job.holds:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(process.pid), 9)
        except OSError:
            pass
    try:
        process.kill()
    except OSError:
        pass


# ---------------------------------------------------------------- run

def run(args: list[str], *, cwd=None, env: dict | None = None, input_text: str | None = None,
        timeout: float | None = None, stall_seconds: float | None = None,
        on_progress: Callable[[dict], None] | None = None, on_line: Callable[[str], None] | None = None) -> Outcome:
    """Runs `args` to completion, or until `timeout` or a stall of `stall_seconds`, then ends its whole tree.
    Never raises for the child's sake; an executable that cannot start raises OSError."""
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, creationflags=creationflags,
                               start_new_session=os.name != "nt")
    job = _Job()
    job.add(process)
    started = time.monotonic()
    out_chunks: list[bytes] = []
    err_lines: list[str] = []
    state = {"progress": None, "position": (), "moved": started, "lines": 0}
    lock = threading.Lock()

    def read_stdout():
        for chunk in iter(lambda: process.stdout.read(65536), b""):
            out_chunks.append(chunk)

    def read_stderr():
        for raw in iter(process.stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            progress = parse_progress(line)
            if progress is None:
                err_lines.append(line)
                if on_line:
                    on_line(line)
                continue
            with lock:
                state["lines"] += 1
                state["progress"] = progress
                if _position(progress) != state["position"]:
                    state["position"], state["moved"] = _position(progress), time.monotonic()
            if on_progress:
                try:
                    on_progress(progress)
                except Exception:   # recording progress must never stop the child
                    pass

    def write_stdin():
        try:
            if input_text is not None:
                process.stdin.write(input_text.encode("utf-8"))
            process.stdin.close()
        except OSError:
            pass

    threads = [threading.Thread(target=t, daemon=True) for t in (read_stdout, read_stderr, write_stdin)]
    for t in threads:
        t.start()

    timed_out = stalled = False
    why = None
    while process.poll() is None:
        try:
            process.wait(timeout=0.5)       # returns as soon as the child exits
            break
        except subprocess.TimeoutExpired:
            pass
        now = time.monotonic()
        if timeout is not None and now - started > timeout:
            timed_out, why = True, f"time limit of {int(timeout)} s reached"
            break
        if stall_seconds is not None:
            with lock:
                quiet = now - state["moved"]
            if quiet > stall_seconds:
                stalled, why = True, f"no progress for {int(quiet)} s (stall limit {int(stall_seconds)} s)"
                break
        # An in-process step the engine asked to stop: the child it is waiting on ends with it (app.workflow.progress).
        from app.workflow import progress as _progress
        if (asked := _progress.stop_requested()) is not None:
            timed_out, why = True, f"the step was stopped: {asked}"
            break

    # Always: whatever the child started and left running ends with it.
    end_tree(process, job, thorough=timed_out or stalled)
    try:
        process.wait(timeout=_EXIT_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    for t in threads:
        t.join(timeout=_READER_GRACE_SECONDS)
    for pipe in (process.stdout, process.stderr):
        try:
            pipe.close()
        except OSError:
            pass
    job.close()
    return Outcome(returncode=process.returncode if not (timed_out or stalled) else None,
                   stdout=b"".join(out_chunks).decode("utf-8", errors="replace"), stderr="\n".join(err_lines),
                   seconds=time.monotonic() - started, timed_out=timed_out, stalled=stalled,
                   last_progress=state["progress"], stopped_why=why, progress_lines=state["lines"])


def describe_position(progress: dict | None) -> str:
    """Where a step was, in words: its phase, items done of the total, and the item."""
    if not progress:
        return "it had reported no progress"
    said = f"phase {progress.get('phase') or '?'}"
    if progress.get("total") is not None:
        said += f", {progress.get('done', 0)} of {progress.get('total')}"
    if progress.get("item"):
        said += f", at {progress['item']}"
    return said


if __name__ == "__main__":     # a tiny child for the tests: python -m app.workflow.processes <mode>
    mode = sys.argv[1]
    if mode == "flood":        # more on stderr than any pipe holds, before any stdout
        sys.stderr.write("x" * 5_000_000 + "\n")
        sys.stdout.write("done\n")
    elif mode == "stall":
        sys.stderr.write(PROGRESS_PREFIX + json.dumps({"phase": "load", "done": 3, "total": 9, "item": "a/b.csproj"}) + "\n")
        sys.stderr.flush()
        while True:            # keeps reporting the same position: alive, but not moving
            time.sleep(1)
            sys.stderr.write(PROGRESS_PREFIX + json.dumps({"phase": "load", "done": 3, "total": 9, "item": "a/b.csproj"}) + "\n")
            sys.stderr.flush()
    elif mode == "spawn":      # starts a grandchild that inherits the pipes and outlives it, then hangs
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        sys.stderr.write(PROGRESS_PREFIX + json.dumps({"phase": "spawned"}) + "\n")
        sys.stderr.flush()
        time.sleep(600)
    elif mode == "leave":      # starts a grandchild that outlives it, then exits by itself at once
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(601)"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        sys.stdout.write("left\n")
