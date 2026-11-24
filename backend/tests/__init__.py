"""Every test run has a database schema and folders of its own (release 7).

Imported before any test module, and before app.config reads its settings: this points DB_SCHEMA at a scratch schema
created for this run, and RUNS_DIR and REPOS_DIR at a scratch folder, then stands the schema up as a new environment
does — migrate to head, then `python -m app.seed` (the platform configuration and the catalog, from the repository
alone; app.seed.reproduce does the same). At the end of the run both are dropped.

So no test reads or writes the schema a running platform uses: a rescan, a reseed or a person working in the UI cannot
make a test fail, and a test cannot change their data. Step programs a test runs are handed this schema in their
database URL and these folders in their context, so they stay inside it too.

A process the run starts (a step, a script) inherits PLATFORM_TEST_SCHEMA and reuses the schema; only the process that
created it drops it. A schema left behind by a run that was killed is dropped by the next run once it is a day old.
"""

import atexit
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_PREFIX = "test_run_"
# The test run's own admin, registered for this machine in the scratch schema only.
TEST_ADMIN_LOGIN = "test-admin"
TEST_ADMIN_PASSWORD = "scratch-schema-admin-only"
_STALE_AFTER = datetime.timedelta(days=1)
# Teardown never hangs: the drop waits at most this long for a lock, ending the run's own sessions before each try.
_DROP_LOCK_TIMEOUT = "30s"
_DROP_ATTEMPTS = 3


def _end_own_sessions(admin, schema: str) -> list[str]:
    """End the sessions this run left open: those named after its schema, and any holding a lock on something in it
    (a test that failed half way can leave a session idle in a transaction, and the drop would wait for it forever).
    Returns one line per session ended, saying what it was doing."""
    from sqlalchemy import text

    with admin.connect() as connection:
        rows = connection.execute(text(
            "SELECT a.pid, a.state, now() - a.state_change AS idle, left(a.query, 160) AS query "
            "FROM pg_stat_activity a WHERE a.pid <> pg_backend_pid() AND a.datname = current_database() AND "
            "(a.application_name = :schema OR a.pid IN (SELECT l.pid FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
            "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = :schema))"), {"schema": schema}).all()
        ended = []
        for pid, state, idle, query in rows:
            connection.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            ended.append(f"session {pid}, {state} for {str(idle).split('.')[0]}: {' '.join((query or '').split())}")
        return ended


def _start() -> None:
    if os.environ.get("PLATFORM_TEST_SCHEMA"):
        os.environ["DB_SCHEMA"] = os.environ["PLATFORM_TEST_SCHEMA"]
        return

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
    schema = f"{_PREFIX}{stamp}_{uuid.uuid4().hex[:6]}"
    folder = Path(tempfile.mkdtemp(prefix="platform-test-run-"))
    (folder / "runs").mkdir()
    (folder / "repos").mkdir()
    os.environ.update({
        "PLATFORM_TEST_SCHEMA": schema,
        # Every connection of this run, and of the processes it starts, is named after its schema, so teardown can
        # find the sessions it left open (_end_own_sessions).
        "PGAPPNAME": schema,
        "DB_SCHEMA": schema,
        "RUNS_DIR": str(folder / "runs"),
        "REPOS_DIR": str(folder / "repos"),
    })

    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    from app.config import settings
    from app.db import make_engine

    assert settings.db_schema == schema, "tests must run in their own schema"
    # Named otherwise than the run's own sessions, so teardown never ends the connection that drops the schema.
    admin = make_engine(settings.database_url, isolation_level="AUTOCOMMIT",
                        connect_args={"application_name": "platform-test-teardown"})
    with admin.connect() as connection:
        for (name,) in connection.execute(text("SELECT nspname FROM pg_namespace WHERE nspname LIKE :p"), {"p": f"{_PREFIX}%"}):
            match = re.match(rf"{_PREFIX}(\d{{14}})_", name)
            if match:
                made = datetime.datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
                if datetime.datetime.now(datetime.timezone.utc) - made > _STALE_AFTER:
                    connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    def _finish() -> None:
        from app.db import engine

        engine.dispose()
        ended = _end_own_sessions(admin, schema)
        dropped = False
        for _ in range(_DROP_ATTEMPTS):
            try:
                with admin.connect() as connection:
                    connection.execute(text(f"SET lock_timeout = '{_DROP_LOCK_TIMEOUT}'"))
                    connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
                dropped = True
                break
            except OperationalError:                        # the lock timeout: a session took a lock meanwhile
                ended += _end_own_sessions(admin, schema)
        admin.dispose()
        shutil.rmtree(folder, ignore_errors=True)
        if ended:
            print(f"\nTest run teardown: ended {len(ended)} database session(s) the run had left open in {schema}:",
                  file=sys.stderr)
            for line in ended:
                print(f"  {line}", file=sys.stderr)
        if not dropped:
            print(f"\nTest run teardown: could not drop the schema {schema} within the time limit; the next test run "
                  f"drops it once it is a day old.", file=sys.stderr)

    atexit.register(_finish)
    for command in (["-m", "alembic", "upgrade", "head"], ["-m", "app.seed"]):
        done = subprocess.run([sys.executable, *command], cwd=_BACKEND, env=os.environ.copy(), capture_output=True, text=True)
        if done.returncode != 0:
            raise SystemExit(f"Standing up the test schema {schema} failed at {' '.join(command[1:])}:\n"
                             f"{done.stdout[-3000:]}\n{done.stderr[-3000:]}")

    # A registered admin for this machine and Windows account, as an installation has after create-first-admin: the
    # command-line tools a test runs act as the registered user running them (app.auth.service.cli_actor).
    from app.auth import machine, service
    from app.db import SessionLocal

    with SessionLocal() as db:
        service.create_user(db, login=TEST_ADMIN_LOGIN, name="Test Admin", windows_account=machine.windows_account(),
                            role="admin", host_names=[machine.hostname()], password=TEST_ADMIN_PASSWORD,
                            must_change_password=False)
        db.commit()


_start()
