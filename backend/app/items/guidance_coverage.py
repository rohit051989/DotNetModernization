"""Whether every active resolution has engine guidance, or is on the reviewed allow-list
(seed/data/engine_guidance_allowlist.yaml, with a reason each). A gap found at release instead of at a client's
conversion, which would otherwise say "no instruction yet" for it (docs/REVIEWING-A-PREPARATION.md)."""
from sqlalchemy.orm import Session

from app import models
from app.engine.inputs.render import allowlist


def active_resolutions(db: Session) -> list[tuple[str, str, str | None]]:
    """[(item id, resolution id, its engine guidance)] of every active, not deleted resolution of every active, not
    deleted catalog item."""
    rows = (db.query(models.ItemResolution.item_id, models.ItemResolution.id, models.ItemResolution.engine_guidance)
            .join(models.CatalogItem, models.CatalogItem.id == models.ItemResolution.item_id)
            .filter(models.CatalogItem.status == "active", models.CatalogItem.deleted_at.is_(None),
                    models.ItemResolution.status == "active", models.ItemResolution.deleted_at.is_(None))
            .order_by(models.ItemResolution.item_id, models.ItemResolution.id))
    return [tuple(r) for r in rows]


def missing(resolutions: list[tuple[str, str, str | None]], allowed: dict[str, str] | None = None) -> list[str]:
    """`item/resolution` for each active resolution with neither guidance nor an allow-list entry."""
    allowed = allowlist() if allowed is None else allowed
    return [f"{item}/{res}" for item, res, text in resolutions if not (text or "").strip() and res not in allowed]


def stale(resolutions: list[tuple[str, str, str | None]], allowed: dict[str, str] | None = None) -> list[str]:
    """Allow-list entries that no longer belong there: the resolution has guidance now, or is not an active one."""
    allowed = allowlist() if allowed is None else allowed
    without = {res for _, res, text in resolutions if not (text or "").strip()}
    return sorted(res for res in allowed if res not in without)
