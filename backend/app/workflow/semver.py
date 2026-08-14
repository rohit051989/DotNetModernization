"""Semver range matching for the step contract — see 11-STEP-CONTRACT.md's
`version_range` rule: npm-style ranges, specifically `^1.0.0`, `~1.2.0`, and
explicit windows like `>=1.0.0 <3.0.0`.

Deliberately hand-rolled rather than a third-party semver package — the
supported grammar is small and fixed by the spec above.
"""

import re

Version = tuple[int, int, int]

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_COMPARATOR_RE = re.compile(r"^(>=|<=|>|<|=)?(\d+\.\d+\.\d+)$")


def parse_version(version: str) -> Version:
    match = _VERSION_RE.match(version.strip())
    if not match:
        raise ValueError(f"'{version}' is not a valid semver version (expected x.y.z)")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def major_version(version: str) -> int:
    return parse_version(version)[0]


def _compare(a: Version, b: Version) -> int:
    return (a > b) - (a < b)


def _caret_bounds(base: Version) -> tuple[Version, Version]:
    """^1.2.3 := >=1.2.3 <2.0.0; ^0.2.3 := >=0.2.3 <0.3.0; ^0.0.3 := >=0.0.3 <0.0.4.
    Caret never lets a change touch the left-most non-zero component."""
    major, minor, patch = base
    if major > 0:
        return base, (major + 1, 0, 0)
    if minor > 0:
        return base, (0, minor + 1, 0)
    return base, (0, 0, patch + 1)


def _tilde_bounds(base: Version) -> tuple[Version, Version]:
    """~1.2.3 := >=1.2.3 <1.3.0 — patch-level changes only."""
    major, minor, _patch = base
    return base, (major, minor + 1, 0)


def satisfies(version: str, version_range: str) -> bool:
    """True if `version` falls within `version_range`."""
    v = parse_version(version)
    version_range = version_range.strip()

    if version_range.startswith("^"):
        lower, upper = _caret_bounds(parse_version(version_range[1:]))
        return _compare(v, lower) >= 0 and _compare(v, upper) < 0

    if version_range.startswith("~"):
        lower, upper = _tilde_bounds(parse_version(version_range[1:]))
        return _compare(v, lower) >= 0 and _compare(v, upper) < 0

    # Explicit window: one or more space-separated comparator clauses, ANDed.
    # A bare version with no operator is treated as an exact match.
    clauses = version_range.split()
    if not clauses:
        raise ValueError("version_range must not be empty")

    for clause in clauses:
        match = _COMPARATOR_RE.match(clause)
        if not match:
            raise ValueError(f"'{clause}' is not a valid range clause in '{version_range}'")
        op, clause_version = match.groups()
        op = op or "="
        cmp = _compare(v, parse_version(clause_version))
        if op == ">=" and cmp < 0:
            return False
        if op == "<=" and cmp > 0:
            return False
        if op == ">" and cmp <= 0:
            return False
        if op == "<" and cmp >= 0:
            return False
        if op == "=" and cmp != 0:
            return False
    return True
