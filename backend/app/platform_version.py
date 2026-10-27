"""The platform version: one for the database, and every developer's copy must match it (docs/VDI-SETUP.md,
"Updating the platform").

Several developers run their own platform against one database. The database is migrated and seeded by one person:
the admin, whose bootstrap records the version it brought the database to (`platform_version`): our commit, from
PLATFORM_SOURCE.json on an installation, or HEAD in our own repository (app.experiment.instrument).

- An admin's bootstrap migrates, seeds, and records the version. So does a first installation's, before any admin
  exists.
- A developer's bootstrap never changes the database. It compares versions and, when they differ, stops with a plain
  message: "the admin has updated; pull the update first" when the database is newer, or "ask the admin to update
  first" when the developer's copy is newer.
- A backend whose version differs from the database's refuses to start, with the same messages. A running backend
  checks every WATCH_SECONDS; once the database moves on (the admin updated), it refuses changes (409
  PLATFORM_UPDATED) and the UI shows a banner asking the person to update and restart.

Which is newer: in our own repository, git knows (one commit is an ancestor of the other); otherwise the commit
dates (PLATFORM_SOURCE.json's `committedAt`, and the database's record). When neither tells, the message says the
two differ and to update so they match.

    python -m app.platform_version show
    python -m app.platform_version gate      (bootstrap: exit 0 migrate and seed, 10 nothing to do, 1 stop)
    python -m app.platform_version record    (bootstrap, after the seed: an admin's, or a first installation's)
"""
import argparse
import datetime
import logging
import sys
import threading
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import machine
from app.experiment import instrument

WATCH_SECONDS = 30
SAME, DATABASE_NEWER, LOCAL_NEWER, UNKNOWN = "same", "database_newer", "local_newer", "unknown"
GATE_MIGRATE, GATE_NOTHING, GATE_STOP = 0, 10, 1
log = logging.getLogger("app.platform_version")


@dataclass(frozen=True)
class Version:
    commit: str | None
    committed_at: datetime.datetime | None = None

    def short(self) -> str:
        return self.commit[:12] if self.commit else "unknown"

    def describe(self) -> str:
        utc = self.committed_at.astimezone(datetime.timezone.utc) if self.committed_at else None
        when = f", committed {utc:%Y-%m-%d %H:%M} UTC" if utc else ""
        return f"{self.short()}{when}"


def _parse(value) -> datetime.datetime | None:
    if isinstance(value, datetime.datetime):
        return value
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)


def _own_repository() -> bool:
    """True when the platform folder is our own git repository (no PLATFORM_SOURCE.json): git knows its history."""
    return instrument.location()["kind"] == "repository" and instrument.source_record() is None


def local() -> Version:
    """This copy's version: our commit, and when it was committed."""
    state = instrument.platform_state()
    commit = state.get("commit")
    if not commit:
        return Version(None)
    if _own_repository():
        return Version(commit, _parse((instrument._git(instrument.PLATFORM_ROOT, "show", "-s", "--format=%cI", commit,
                                                       check=False) or "").strip()))
    record = instrument.source_record() or {}
    return Version(commit, _parse(record.get("committedAt")))


def database(db: Session) -> Version | None:
    """The database's version: the newest recorded; None before any is (or before the table exists)."""
    if db.execute(text("SELECT to_regclass('platform_version')")).scalar() is None:
        return None
    row = db.execute(text("SELECT commit, committed_at FROM platform_version ORDER BY id DESC LIMIT 1")).first()
    return Version(row.commit, row.committed_at) if row else None


def _git_order(mine: str, theirs: str) -> str | None:
    """In our own repository: which of the two commits is newer, when one is an ancestor of the other."""
    if not _own_repository():
        return None
    root = instrument.PLATFORM_ROOT
    for commit in (mine, theirs):
        if instrument._git(root, "cat-file", "-e", f"{commit}^{{commit}}", check=False) is None:
            return None
    if instrument._git(root, "merge-base", "--is-ancestor", theirs, mine, check=False) is not None:
        return LOCAL_NEWER
    if instrument._git(root, "merge-base", "--is-ancestor", mine, theirs, check=False) is not None:
        return DATABASE_NEWER
    return None


def compare(mine: Version, theirs: Version | None) -> str:
    if theirs is None:
        return LOCAL_NEWER                       # the database records no version yet: the admin has not updated
    if not mine.commit:
        return UNKNOWN
    if mine.commit == theirs.commit:
        return SAME
    order = _git_order(mine.commit, theirs.commit)
    if order:
        return order
    if mine.committed_at and theirs.committed_at and mine.committed_at != theirs.committed_at:
        return LOCAL_NEWER if mine.committed_at > theirs.committed_at else DATABASE_NEWER
    return UNKNOWN


def message(state: str, mine: Version, theirs: Version | None) -> str | None:
    if state == SAME:
        return None
    if state == DATABASE_NEWER:
        return (f"The admin has updated the platform: the database is at {theirs.describe()}, and this copy is at "
                f"{mine.describe()}. Pull the update first (docs/VDI-SETUP.md, \"Updating the platform\"), then run "
                "bootstrap and start the backend again.")
    if state == LOCAL_NEWER:
        at = theirs.describe() if theirs else "a version from before versions were recorded"
        return (f"This copy of the platform ({mine.describe()}) is newer than the database ({at}): ask the admin to "
                "update first, then run bootstrap and start the backend again.")
    return (f"This copy of the platform ({mine.describe()}) and the database ({theirs.describe() if theirs else 'none'}) "
            "are at different versions, and which is newer cannot be told here: ask the admin which to use, and update "
            "so the two match.")


class VersionMismatch(RuntimeError):
    """This copy of the platform is not at the database's version."""


def check_at_start() -> Version:
    """Refuses (VersionMismatch, with the plain message) unless this copy is at the database's version. Returns it."""
    from app.db import SessionLocal

    mine = local()
    with SessionLocal() as db:
        theirs = database(db)
    if why := message(compare(mine, theirs), mine, theirs):
        raise VersionMismatch(why)
    return mine


# ---------- a running backend: the admin may update while it runs ----------

_changed: dict | None = None


def updated() -> dict | None:
    """Once the database has moved on while this backend runs: {"running", "database", "message"}; else None."""
    return _changed


class Watch:
    """Checks the database's version every WATCH_SECONDS against the one this backend started at."""

    def __init__(self, running: Version) -> None:
        self.running = running
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        global _changed
        _changed = None
        self._thread = threading.Thread(target=self._run, name="platform-version", daemon=True)
        self._thread.start()

    def check(self) -> None:
        global _changed
        from app.db import SessionLocal

        with SessionLocal() as db:
            theirs = database(db)
        if theirs is not None and theirs.commit != self.running.commit:
            state = compare(self.running, theirs)
            why = message(state if state != SAME else UNKNOWN, self.running, theirs)
            if _changed is None:
                log.warning("The database's platform version changed while this backend runs: %s", why)
            _changed = {"running": self.running.commit, "database": theirs.commit,
                        "message": why + " Until then, nothing can be changed from this backend."}

    def _run(self) -> None:
        while not self._stop.wait(WATCH_SECONDS):
            try:
                self.check()
            except Exception:       # a database blip must not stop the platform; the next check retries
                log.exception("platform version check failed")

    def stop(self) -> None:
        self._stop.set()


# ---------- bootstrap ----------


def _who(db: Session) -> tuple[str, str | None]:
    """('first', None) before any admin exists; ('admin' | 'developer' | 'unregistered', label) otherwise. Read with
    plain SQL, so it works whatever version the database's tables are at."""
    if db.execute(text("SELECT to_regclass('users')")).scalar() is None:
        return "first", None
    if not db.execute(text("SELECT count(*) FROM users WHERE role = 'admin' AND deactivated_at IS NULL")).scalar():
        return "first", None
    row = db.execute(text("""
        SELECT u.role, u.name, u.login FROM users u JOIN user_hosts h ON h.user_id = u.id
        WHERE lower(u.windows_account) = lower(:account) AND lower(h.hostname) = lower(:host) AND u.deactivated_at IS NULL
    """), {"account": machine.windows_account(), "host": machine.hostname()}).first()
    if row is None:
        return "unregistered", None
    return row.role, f"{row.name} ({row.login})"


def gate(db: Session, out=print) -> int:
    """For bootstrap, before its migration: GATE_MIGRATE for an admin or a first installation; else GATE_NOTHING when
    this copy is at the database's version, or GATE_STOP with the message saying what to do."""
    who, label = _who(db)
    mine = local()
    if who == "first":
        out(f"No admin exists yet: a first installation. Migrating and seeding; the database will be at {mine.describe()}.")
        return GATE_MIGRATE
    theirs = database(db)
    state = compare(mine, theirs)
    if who == "admin":
        if state == DATABASE_NEWER:
            # An older copy must not take the database back.
            out(message(state, mine, theirs))
            return GATE_STOP
        out(f"{label} is an admin: migrating and seeding; the database will be at {mine.describe()}.")
        return GATE_MIGRATE
    if state == SAME:
        out(f"The database is at this version ({mine.describe()}): nothing to migrate or seed. Only the admin's "
            "bootstrap changes the database.")
        return GATE_NOTHING
    out(message(state, mine, theirs))
    return GATE_STOP


def record(db: Session, out=print) -> int:
    """After an admin's (or a first installation's) migration and seed: the database is at this version now."""
    who, label = _who(db)
    if who not in ("first", "admin"):
        out("Only the admin's bootstrap records the platform version.")
        return 1
    mine = local()
    if not mine.commit:
        out("This copy's commit is not known (no PLATFORM_SOURCE.json, and not our git repository): nothing recorded. "
            "Run scripts\\update-platform.ps1, which writes PLATFORM_SOURCE.json.")
        return 1
    theirs = database(db)
    if theirs is not None and theirs.commit == mine.commit:
        out(f"The database is at {mine.describe()} already.")
        return 0
    head = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    db.execute(text("INSERT INTO platform_version (commit, committed_at, migration, recorded_by, hostname) "
                    "VALUES (:c, :at, :m, :by, :h)"),
               {"c": mine.commit, "at": mine.committed_at, "m": head,
                "by": label or f"first installation ({machine.windows_account()})", "h": machine.hostname()})
    db.commit()
    out(f"The database is at {mine.describe()} now. Every developer pulls this update, runs bootstrap and restarts "
        "their backend.")
    return 0


def main(argv: list[str] | None = None) -> int:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(prog="python -m app.platform_version",
                                     description="The platform version: this copy's, and the database's.")
    parser.add_argument("command", choices=("show", "gate", "record"))
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        if args.command == "gate":
            return gate(db)
        if args.command == "record":
            return record(db)
        mine, theirs = local(), database(db)
        print(f"This copy:    {mine.describe()}")
        print(f"The database: {theirs.describe() if theirs else 'no version recorded yet'}")
        print(message(compare(mine, theirs), mine, theirs) or "The same version.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
