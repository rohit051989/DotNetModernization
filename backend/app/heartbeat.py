"""One platform backend per machine (docs/VDI-SETUP.md: More than one person).

Several developers each run their own backend against one database: backends on different machines run side by
side. Each runs its jobs in its own process (BackgroundTasks), takes only jobs queued on its own machine
(app.workflow.runtime), and, when it starts, fails only its own machine's jobs left running: a previous process of
its own must have died. A second backend started on the same machine would fail the first one's running jobs at
once, so each running backend keeps a heartbeat row for its machine, and a backend that finds a fresh one for its
machine, from a process still alive, refuses to start before it touches anything.

A heartbeat expires STALE (90 s) after its last beat. It is taken over at once when the process that wrote it no
longer exists (a restart, a killed process, or `--reload` replacing its worker). Its age is measured on the
database's clock alone. `online()` lists the machines with a fresh heartbeat: who is online, and where.

    python -m app.heartbeat show
    python -m app.heartbeat clear          (this machine's heartbeat, known to be stale)

Command-line tools (bootstrap, the seed, the repositories and engagements commands) take no heartbeat: they do not
run the job engine's startup.
"""
import argparse
import datetime
import getpass
import logging
import os
import sys
import threading
import uuid
from dataclasses import dataclass

from sqlalchemy import func, text

from app import models
from app.auth import machine
from app.config import settings
from app.db import SessionLocal

INTERVAL_SECONDS = 20
STALE = datetime.timedelta(seconds=90)
log = logging.getLogger("app.heartbeat")


class AnotherPlatform(RuntimeError):
    """Another platform backend is running on this machine."""


@dataclass
class Me:
    instance_id: uuid.UUID
    host: str
    os_user: str
    pid: int
    platform_root: str
    api_port: int | None


def me() -> Me:
    return Me(uuid.uuid4(), machine.hostname(), getpass.getuser(), os.getpid(), settings.platform_root, settings.api_port)


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


def _key(host: str) -> str:
    return host.strip().lower()


def refusal(row, mine: Me, age: datetime.timedelta | None, alive=pid_alive) -> str | None:
    """Why this backend must not start while `row` (this machine's heartbeat), last renewed `age` ago by the
    database's clock, stands; or None."""
    if row is None or row.instance_id == mine.instance_id:
        return None
    if age is None or age > STALE:
        return None
    if not alive(row.pid):
        return None
    left = int((STALE - age).total_seconds()) + 1
    return (f"Another Modernization Platform backend is already running on this machine ({row.host}): started "
            f"{row.started_at:%Y-%m-%d %H:%M} UTC by {row.os_user} (process {row.pid}, {row.platform_root}, port "
            f"{row.api_port}), last seen {int(age.total_seconds())} s ago. One backend runs per machine: two would fail "
            "each other's running jobs. Use the one that is running, or stop it (Ctrl+C in its window) and start this "
            f"one (docs/VDI-SETUP.md: More than one person). A heartbeat expires {int(STALE.total_seconds())} s after "
            f"its last beat; if that backend has stopped without shutting down, start again in {left} s, or clear it: "
            f"{CLEAR_COMMAND}")


def _current(db, host: str):
    """This machine's heartbeat row and its age by the database's clock, or (None, None)."""
    found = db.execute(text("SELECT now() - beat_at FROM platform_backends WHERE host = :h"), {"h": _key(host)}).first()
    if found is None:
        return None, None
    return db.get(models.PlatformBackend, _key(host)), found[0]


def claim(mine: Me, alive=pid_alive) -> None:
    """Takes this machine's heartbeat, or raises AnotherPlatform. The table is locked for the check, so two backends
    starting at once on one machine cannot both take it."""
    with SessionLocal() as db:
        db.execute(text("LOCK TABLE platform_backends IN EXCLUSIVE MODE"))
        row, age = _current(db, mine.host)
        reason = refusal(row, mine, age, alive)
        if reason:
            db.rollback()
            raise AnotherPlatform(reason)
        if row is None:
            row = models.PlatformBackend(host=_key(mine.host))
            db.add(row)
        row.instance_id, row.os_user, row.pid = mine.instance_id, mine.os_user, mine.pid
        row.platform_root, row.api_port = mine.platform_root, mine.api_port
        row.started_at, row.beat_at = func.now(), func.now()
        db.commit()


def beat(mine: Me) -> bool:
    """Refreshes the heartbeat. False when another backend on this machine took it over."""
    with SessionLocal() as db:
        done = db.execute(text("UPDATE platform_backends SET beat_at = now() WHERE host = :h AND instance_id = :i"),
                          {"h": _key(mine.host), "i": mine.instance_id})
        db.commit()
        return done.rowcount == 1


def release(mine: Me) -> None:
    with SessionLocal() as db:
        db.execute(text("DELETE FROM platform_backends WHERE host = :h AND instance_id = :i"),
                   {"h": _key(mine.host), "i": mine.instance_id})
        db.commit()


def online(db) -> list[dict]:
    """The machines with a running backend (a fresh heartbeat), each with the person most recently signed in there."""
    from app.auth import service

    people = service.live_session_by_host(db)
    rows = db.execute(text("SELECT host, started_at, beat_at, now() - beat_at AS age FROM platform_backends "
                           "ORDER BY host")).all()
    found = []
    for row in rows:
        if row.age > STALE:
            continue
        user = people.get(row.host)
        found.append({"host": row.host, "since": row.started_at, "last_seen": row.beat_at,
                      "user_name": user.name if user else None, "user_login": user.login if user else None})
    return found


class Heartbeat:
    """Claims this machine at start, beats every INTERVAL_SECONDS in a daemon thread, releases it at shutdown."""

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
                    log.error("This backend's heartbeat was taken over by another backend on this machine (%s): stop "
                              "one of them (docs/VDI-SETUP.md: More than one person).", self.mine.host)
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
        return "No backend runs on this machine."
    state = (f"expired ({int(age.total_seconds())} s since its last beat; a heartbeat expires after "
             f"{int(STALE.total_seconds())} s)" if age > STALE
             else f"live: last beat {int(age.total_seconds())} s ago")
    return (f"This machine ({row.host}): {row.os_user}, process {row.pid}, {row.platform_root}, port {row.api_port}, "
            f"started {row.started_at:%Y-%m-%d %H:%M} UTC: {state}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.heartbeat",
                                     description="Show the backends running against this database, or clear this "
                                                 "machine's heartbeat.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    clear = sub.add_parser("clear", help="remove this machine's heartbeat, known to be stale, so a backend can start now")
    clear.add_argument("--yes", action="store_true", help="do not ask")
    args = parser.parse_args(argv)
    host = machine.hostname()
    print(f"{settings.db_name}, schema {settings.db_schema}")
    with SessionLocal() as db:
        if args.command == "show":
            for entry in online(db):
                print(f"  online: {entry['host']}{' (' + entry['user_name'] + ')' if entry['user_name'] else ''}, "
                      f"since {entry['since']:%Y-%m-%d %H:%M} UTC")
        row, age = _current(db, host)
        print(describe(row, age))
        if args.command == "show" or row is None:
            return 0
        from app.auth import service

        service.cli_actor(db)
        if pid_alive(row.pid) and age <= STALE:
            print(f"Process {row.pid} is still running on this machine: stop that backend (Ctrl+C in its window) "
                  "instead. Nothing cleared.")
            return 1
        if not args.yes and age <= STALE:
            answer = input("Only clear it if you know that backend has stopped. Type clear to remove it: ")
            if answer.strip() != "clear":
                print("Nothing cleared.")
                return 1
        db.execute(text("DELETE FROM platform_backends WHERE host = :h"), {"h": _key(host)})
        db.commit()
        print("Cleared: a backend can start on this machine now.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
