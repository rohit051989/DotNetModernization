"""The reproduce check (app.seed.reproduce) as a suite: scripts\\run-suites.ps1 runs it when seed data,
registrations, the catalog or migrations change.

    python -m tests.reproduce_on_scratch

Importing `tests` first gives the run a scratch schema of its own, stood up from the repository alone (migrate,
then seed), and points DB_SCHEMA at it; reproduce then stands up a second one the same way and compares the two. So
it proves that the repository bootstraps a platform, and the same platform every time, without reading or changing
the schema a running platform uses. This machine's own schema is compared by `python -m app.seed.reproduce` itself
(CLAUDE.md rule 11), once this machine has been bootstrapped at the commit.

Not a test module (no test_ prefix): unittest discovery leaves it alone.
"""
import sys

import tests  # noqa: F401  the scratch schema, before app.config reads its settings
from app.seed import reproduce

if __name__ == "__main__":
    sys.argv = sys.argv[:1]
    sys.exit(reproduce.main())
