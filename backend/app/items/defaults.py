"""Exactly one default resolution per active item.

uq_item_resolutions_one_default gives at most one live default; the deferred
constraint trigger trg_item_resolutions_one_default (migration b3e1c7a2d9f4)
gives at least one, at commit. This module is the readable side of that rule:
it lists the items that break it, and the seed and the catalog import check it
before they commit, so a broken default is reported naming the item rather
than surfacing as a database error.

The rule: an active, live item with any live, active resolution has exactly
one live default, and that default is active. An item with no live, active
resolution has nothing to default to and is not checked.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

_QUERY = text("""
    SELECT i.id,
           count(r.id) FILTER (WHERE r.is_default) AS defaults,
           count(r.id) FILTER (WHERE r.is_default AND r.status <> 'active') AS inactive_defaults,
           string_agg(r.id, ', ' ORDER BY r.id) FILTER (WHERE r.status = 'active') AS live
    FROM catalog_items i
    JOIN item_resolutions r ON r.item_id = i.id AND r.deleted_at IS NULL
    WHERE i.deleted_at IS NULL AND i.status = 'active'
    GROUP BY i.id
    HAVING count(r.id) FILTER (WHERE r.status = 'active') > 0
       AND (count(r.id) FILTER (WHERE r.is_default) <> 1
            OR count(r.id) FILTER (WHERE r.is_default AND r.status <> 'active') > 0)
    ORDER BY i.id
""")


def violations(db: Session) -> list[dict]:
    """Every active item without exactly one live, active default."""
    db.flush()
    return [
        {"item_id": row.id, "defaults": row.defaults, "inactive_defaults": row.inactive_defaults, "live_resolutions": row.live}
        for row in db.execute(_QUERY)
    ]


def describe(violation: dict) -> str:
    if violation["inactive_defaults"]:
        return f"{violation['item_id']}: its default is not active (live resolutions: {violation['live_resolutions']})"
    return (f"{violation['item_id']}: {violation['defaults']} defaults, needs exactly one "
            f"(live resolutions: {violation['live_resolutions']})")


def check(db: Session, where: str) -> None:
    """Raises ValueError naming every item without exactly one default."""
    found = violations(db)
    if found:
        raise ValueError(f"{where}: every active item needs exactly one default resolution:\n  "
                         + "\n  ".join(describe(v) for v in found))
