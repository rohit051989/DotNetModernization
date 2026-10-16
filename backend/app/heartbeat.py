"""One platform per schema (docs/VDI-SETUP.md section N).

The platform runs its jobs in its own process (BackgroundTasks) and, when it starts, fails every job it finds still
running: a previous process of its own must have died. A second platform started on the same schema — a second
person, or the same person twice — would fail the first one's running jobs at once, and then each would run the
other's work. So a running platform keeps one heartbeat row in its schema, and a platform that finds another's fresh
heartbeat refuses to start, before it touches anything.

A heartbeat expires STALE (90 s) after its last beat, so a platform that stopped without shutting down — its VDI
session closed, its process killed, its machine restarted — blocks the next start for at most that long. It is
taken over at once when it was written on this machine by a process that no longer exists (a restart, a killed
process, or `--reload` replacing its worker). Its age is measured on the database's clock alone, so machines whose
clocks disagree cannot keep it alive. One known to be stale can be cleared at once:

    python -m app.heartbeat show
    python -m app.heartbeat clear

Command-line tools (bootstrap, the seed, the repositories and engagements commands) take no heartbeat: they do not
run the job engine's startup.
"""
import argparse
import datetime
import getpass
import logging
import os
import socket
import sys
import threading
import uuid
from dataclasses import dataclass

from sqlalchemy import func, text

from app import models
from app.config import settings
from app.db import SessionLocal

INTERVAL_SECONDS = 20
STALE = datetime.timedelta(seconds=90)
log = logging.getLogger("app.heartbeat")


class AnotherPlatform(RuntimeError):
    """Another platform is running on this schema."""


@dataclass
class Me:
    instance_id: uuid.UUID
    host: str
    os_user: str
    pid: int
    platform_root: str
    api_port: int | None


def me() -> Me:
    return Me(uuid.uuid4(), socket.gethostname(), getpass.getuser(), os.getpid(), settings.platform_root,
              settings.api_port)


def pid_alive(pid: int) -> bool:
    """Whether a process with this id exists on this machine. Windows: OpenProcess and its exit code (os.kill with
    signal 0 would send Ctrl+C there)."""
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5                   # access denied: it exists; else it does not
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


CLEAR_COMMAND = r"cd backend; .venv\Scripts\python.exe -m app.heartbeat clear"


def refusal(row, mine: Me, age: datetime.timedelta | None, alive=pid_alive) -> str | None:
    """Why this platform must not start while `row` (the schema's heartbeat), last renewed `age` ago by the
    database's clock, stands; or None."""
    if row is None or row.instance_id == mine.instance_id:
        return None
    if age is None or age > STALE:
        return None
    if row.host == mine.host and not alive(row.pid):
        return None
    where = f"{settings.db_name}, schema {settings.db_schema}"
    left = int((STALE - age).total_seconds()) + 1
    return (f"Another Modernization Platform is already running on {where}: started "
            f"{row.started_at:%Y-%m-%d %H:%M} UTC by {row.os_user} on {row.host} (process {row.pid}, "
            f"{row.platform_root}, port {row.api_port}), last seen {int(age.total_seconds())} s ago. Two platforms on "
            "one schema would fail each other's running jobs and run each other's work, so this one does not start. "
            "Each person needs their own schema: give this one its own DB_SCHEMA and RUNS_DIR in backend\\.env "
            f"(docs/VDI-SETUP.md section N). A heartbeat expires {int(STALE.total_seconds())} s after its last beat: "
            f"if that platform has stopped without shutting down (its VDI session closed, its machine restarted), "
            f"start again in {left} s, or, if you know it has stopped, clear it now: {CLEAR_COMMAND}")


def _current(db):
    """The heartbeat row and its age by the database's clock, or (None, None)."""
    found = db.execute(text("SELECT now() - beat_at FROM platform_heartbeat WHERE id = 1")).first()
    if found is None:
        return None, None
    return db.get(models.PlatformHeartbeat, 1), found[0]


def claim(mine: Me) -> None:
    """Takes this schema's heartbeat, or raises AnotherPlatform. The table is locked for the check, so two platforms
    starting at once cannot both take it."""
    with SessionLocal() as db:
        db.execute(text("LOCK TABLE platform_heartbeat IN EXCLUSIVE MODE"))
        row, age = _current(db)
        reason = refusal(row, mine, age)
        if reason:
            db.rollback()
            raise AnotherPlatform(reason)
        if row is None:
            row = models.PlatformHeartbeat(id=1)
            db.add(row)
        row.instance_id, row.host, row.os_user, row.pid = mine.instance_id, mine.host, mine.os_user, mine.pid
        row.platform_root, row.api_port = mine.platform_root, mine.api_port
        row.started_at, row.beat_at = func.now(), func.now()
        db.commit()


def beat(mine: Me) -> bool:
    """Refreshes the heartbeat. False when another platform took it over (this one then logs it on every beat)."""
    with SessionLocal() as db:
        done = db.execute(text("UPDATE platform_heartbeat SET beat_at = now() WHERE id = 1 AND instance_id = :i"),
                          {"i": mine.instance_id})
        db.commit()
        return done.rowcount == 1


def release(mine: Me) -> None:
    with SessionLocal() as db:
        db.execute(text("DELETE FROM platform_heartbeat WHERE id = 1 AND instance_id = :i"), {"i": mine.instance_id})
        db.commit()


class Heartbeat:
    """Claims the schema at start, beats every INTERVAL_SECONDS in a daemon thread, releases it at shutdown."""

    def __init__(self) -> None:
        self.mine = me()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        claim(self.mine)
        self._thread = threading.Thread(target=self._run, name="platform-heartbeat", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(INTERVAL_SECONDS):
            try:
                if not beat(self.mine):
                    log.error("This platform's heartbeat was taken over by another platform on schema %s: stop one "
                              "of them (docs/VDI-SETUP.md section N).", settings.db_schema)
            except Exception:        # a database blip must not stop the platform; the next beat retries
                log.exception("heartbeat failed")

    def stop(self) -> None:
        self._stop.set()
        try:
            release(self.mine)
        except Exception:
            log.exception("could not release the heartbeat")


def describe(row, age: datetime.timedelta | None) -> str:
    if row is None:
        return "No platform holds this schema."
    state = (f"expired ({int(age.total_seconds())} s since its last beat; a heartbeat expires after "
             f"{int(STALE.total_seconds())} s)" if age > STALE
             else f"live: last beat {int(age.total_seconds())} s ago")
    return (f"Held by {row.os_user} on {row.host}, process {row.pid}, {row.platform_root}, port {row.api_port}, "
            f"started {row.started_at:%Y-%m-%d %H:%M} UTC: {state}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.heartbeat",
                                     description="Show or clear the heartbeat of the platform holding this schema.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    clear = sub.add_parser("clear", help="remove a heartbeat known to be stale, so the platform can start at once")
    clear.add_argument("--yes", action="store_true", help="do not ask")
    args = parser.parse_args(argv)
    print(f"{settings.db_name}, schema {settings.db_schema}")
    with SessionLocal() as db:
        row, age = _current(db)
        print(describe(row, age))
        if args.command == "show" or row is None:
            return 0
        if row.host == socket.gethostname() and pid_alive(row.pid) and age <= STALE:
            print(f"Process {row.pid} is still running on this machine: stop that platform (Ctrl+C in its window) "
                  "instead. Nothing cleared.")
            return 1
        if not args.yes and age <= STALE:
            answer = input(f"Only clear it if you know that platform has stopped: two platforms on one schema fail "
                           "each other's jobs. Type clear to remove it: ")
            if answer.strip() != "clear":
                print("Nothing cleared.")
                return 1
        db.execute(text("DELETE FROM platform_heartbeat WHERE id = 1"))
        db.commit()
        print("Cleared: a platform can start on this schema now.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
