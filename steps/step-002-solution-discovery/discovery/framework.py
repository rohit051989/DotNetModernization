"""Raw target framework -> family/version normalisation, for dashboard
grouping only. `target_framework_raw`/`target_frameworks_raw` always keep
the verbatim declared value(s) separately — this module never overwrites
them. See 19-STEP-002-SOLUTION-DISCOVERY.md Part E.
"""

import re

_LEGACY_DOTTED_RE = re.compile(r"^v(\d+(?:\.\d+)*)$", re.IGNORECASE)
_NET_MODERN_RE = re.compile(r"^net(\d+)\.(\d+)(?:-([a-zA-Z0-9.]+))?$", re.IGNORECASE)
_NET_FRAMEWORK_SHORT_RE = re.compile(r"^net(\d{2,3})$", re.IGNORECASE)
_NETCOREAPP_RE = re.compile(r"^netcoreapp(\d+(?:\.\d+)*)$", re.IGNORECASE)
_NETSTANDARD_RE = re.compile(r"^netstandard(\d+(?:\.\d+)*)$", re.IGNORECASE)

# Recency order used to pick the "highest" framework in a multi-targeting
# project — comparing across families only makes sense as "most modern".
FAMILY_RANK = {"unknown": -1, "net-framework": 0, "net-standard": 1, "net-core": 2, "net": 3}


def normalize_one(raw: str) -> tuple[str, str | None, str | None]:
    """(family, version, platform_suffix) for a single raw TFM token."""
    if not raw:
        return "unknown", None, None
    token = raw.strip()

    match = _NET_MODERN_RE.match(token)
    if match:
        major, minor, suffix = match.groups()
        return "net", f"{major}.{minor}", suffix

    match = _NETCOREAPP_RE.match(token)
    if match:
        return "net-core", match.group(1), None

    match = _NETSTANDARD_RE.match(token)
    if match:
        return "net-standard", match.group(1), None

    match = _NET_FRAMEWORK_SHORT_RE.match(token)
    if match:
        digits = match.group(1)
        major, minor, patch = digits[0], digits[1], digits[2:]
        version = f"{major}.{minor}" + (f".{patch}" if patch else "")
        return "net-framework", version, None

    match = _LEGACY_DOTTED_RE.match(token)
    if match:
        return "net-framework", match.group(1), None

    return "unknown", None, None


def _version_tuple(version: str | None) -> tuple[int, ...]:
    if not version:
        return ()
    return tuple(int(part) for part in re.findall(r"\d+", version))


def resolve(target_frameworks_raw: list[str]) -> tuple[str | None, str | None, bool, str | None]:
    """`target_frameworks_raw` is the project's full declared list (length 1
    unless multi-targeting). Returns
    (framework_family, framework_version, is_multi_targeting, warning).

    For multi-targeting, family/version reflect the highest (most modern)
    framework present, and a warning records that choice so it stays
    visible (Part E: "Record the reasoning in a parse warning").
    """
    normalized = [(raw, *normalize_one(raw)) for raw in target_frameworks_raw]
    is_multi = len(target_frameworks_raw) > 1

    if not is_multi:
        raw, family, version, suffix = normalized[0]
        warning = None
        if suffix:
            warning = f"target framework '{raw}' has platform suffix '{suffix}', not modelled as a separate column"
        return family, version, False, warning

    best_raw, best_family, best_version, _suffix = max(
        normalized, key=lambda item: (FAMILY_RANK.get(item[1], -1), _version_tuple(item[2]))
    )
    raw_list = ", ".join(raw for raw, *_ in normalized)
    warning = (
        f"multi-targeting ({raw_list}); framework_family/framework_version reflect the highest "
        f"version present ('{best_raw}' -> {best_family} {best_version})"
    )
    return best_family, best_version, True, warning
