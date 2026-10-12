"""Conversion — the minimum of 34-CONVERSION-ARCHITECTURE.md (C1, C4, E, F).

Recipes wrap approaches (recipes.py, recipes.yaml); a plan expands them over a
repository into ordered units (planner.py, with the ordering by framework
support in frameworks.py); the unit loop applies each unit in its own scratch
git worktree, checks, builds and tests it, and commits only what is green
(runner.py). Approaches are deterministic code (approaches.py, msbuild.py).
Evidence is files with their sha256 (evidence.py), never a claim.

    python -m app.conversion.planner --repository eshoponweb --exclude-package Ardalis.Specification --exclude-package MSTest.TestFramework
    python -m app.conversion.runner --plan <plan-id>
    python -m app.conversion.runner --plan <plan-id> --exclude <sequence> --reason "..."
"""
