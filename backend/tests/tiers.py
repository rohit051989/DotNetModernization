"""The two tiers of the backend test suite (scripts\\run-suites.ps1, scripts\\backend_shards.py).

The quick tier, the default while working, leaves out the tests marked slow; the full tier runs every test, once, on
the tip of master before a push (CLAUDE.md rule 17). Mark a test class or method slow when it takes a minute or more
(it scans a sample, builds a repository, or stands up a schema of its own); never delete one for being slow.

    from tests.tiers import slow

    @slow
    class ScanOfASample(unittest.TestCase): ...

The tier comes from PLATFORM_TESTS_TIER ("quick" or "full"); unset means full, so python -m unittest runs everything.
"""
import os
import unittest

QUICK = os.environ.get("PLATFORM_TESTS_TIER", "full").strip().lower() == "quick"

slow = unittest.skipIf(QUICK, "slow: the full tier runs it (tests/tiers.py)")
