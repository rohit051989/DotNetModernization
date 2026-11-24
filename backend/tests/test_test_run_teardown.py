"""A test run never hangs on its teardown (backend\\tests\\__init__.py).

A test that fails half way can leave a database session idle in a transaction, holding a lock in the run's schema;
the schema's drop at the end of the run used to wait for it forever. Teardown now ends the run's own sessions, reports
each one it ended, and gives the drop a time limit.
"""
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from sqlalchemy import text

from app.db import engine

BACKEND = Path(__file__).resolve().parents[1]

# A run of its own (a schema of its own) whose only work leaves a session idle in a transaction, holding a lock on a
# table of its schema, and exits without closing it.
LEAVES_A_SESSION_OPEN = """
import os
import tests
from app import models
from app.db import SessionLocal

leaked = SessionLocal()
leaked.query(models.Engagement).count()
print("SCHEMA=" + os.environ["PLATFORM_TEST_SCHEMA"], flush=True)
"""


class TeardownTests(unittest.TestCase):
    def test_a_session_left_open_is_ended_and_reported_and_the_schema_dropped(self):
        env = {k: v for k, v in os.environ.items() if k not in ("PLATFORM_TEST_SCHEMA", "PGAPPNAME")}
        began = time.monotonic()
        done = subprocess.run([sys.executable, "-c", LEAVES_A_SESSION_OPEN], cwd=BACKEND, env=env, capture_output=True,
                              text=True, timeout=600)
        taken = time.monotonic() - began
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        schema = next(line[7:] for line in done.stdout.splitlines() if line.startswith("SCHEMA="))
        self.assertIn(f"ended 1 database session(s) the run had left open in {schema}", done.stderr)
        self.assertIn("idle in transaction", done.stderr)
        self.assertNotIn("could not drop", done.stderr)
        with engine.connect() as connection:
            left = connection.execute(text("SELECT count(*) FROM pg_namespace WHERE nspname = :s"), {"s": schema}).scalar()
        self.assertEqual(left, 0, f"{schema} was not dropped")
        self.assertLess(taken, 300, "standing up and tearing down a run took far longer than it should")


if __name__ == "__main__":
    unittest.main()
