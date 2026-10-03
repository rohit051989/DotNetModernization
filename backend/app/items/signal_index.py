"""The signal ↔ item index — 28-ITEM-AND-CONVERSION-MODEL.md Part H.

Which catalog items reference which signals, and how. Built server-side from
each item's stored detection so every consumer (the signal coverage view,
item detail) sees one answer instead of re-parsing detection rules.

A reference has one or more usages:

- `match` — the signal is in `all`, `any` or `atLeast`: its presence helps
  the item apply.
- `none` — the signal is in `none`: its presence stops the item applying.
  A signal used ONLY this way is doing exclusion work, not detection, and is
  reported that way (`exclusion_only`).
- `occurrence_source` — the signal's evidence locates the item's
  occurrences.

Soft-deleted items are left out; deprecated items are included and marked,
since their references still describe the catalog's history.
"""

from sqlalchemy.orm import Session

from app import models

USAGES = ("match", "none", "occurrence_source")


def item_signal_usages(detection: dict) -> dict[str, set[str]]:
    """signal name -> the usages it has in one item's detection."""
    usages: dict[str, set[str]] = {}
    match = detection.get("match", {})

    def add(name: str, usage: str) -> None:
        usages.setdefault(name, set()).add(usage)

    for group in ("all", "any"):
        for condition in match.get(group, []):
            add(condition["signal"]["name"], "match")
    for group in match.get("atLeast", []):
        for condition in group.get("of", []):
            add(condition["signal"]["name"], "match")
    for condition in match.get("none", []):
        add(condition["signal"]["name"], "none")
    source = detection.get("occurrence_source")
    if source:
        for name in [source["signal"], *(source.get("also") or [])]:
            add(name, "occurrence_source")
    return usages


def _sorted_usages(usages: set[str]) -> list[str]:
    return [u for u in USAGES if u in usages]


def _live_items(db: Session) -> list[models.CatalogItem]:
    return (
        db.query(models.CatalogItem)
        .filter(models.CatalogItem.deleted_at.is_(None))
        .order_by(models.CatalogItem.id)
        .all()
    )


def signal_index(db: Session) -> list[dict]:
    """Every registered signal, plus any name an item references that is not
    registered, each with the items referencing it. Sorted by name."""
    references: dict[str, list[dict]] = {}
    for item in _live_items(db):
        for name, usages in item_signal_usages(item.detection).items():
            references.setdefault(name, []).append({
                "item_id": item.id,
                "item_name": item.name,
                "item_scope": item.scope,
                "item_status": item.status,
                "usages": _sorted_usages(usages),
            })

    rows = []
    registered = {s.name: s for s in db.query(models.SignalRegistryEntry)}
    for name in sorted(set(registered) | set(references)):
        signal = registered.get(name)
        refs = references.get(name, [])
        all_usages = {u for r in refs for u in r["usages"]}
        rows.append({
            "name": name,
            "registered": signal is not None,
            "type": signal.type if signal else None,
            "category": signal.category if signal else None,
            "expected_extractor": signal.expected_extractor if signal else None,
            "state": signal.state if signal else None,
            "signal_introduced_in_version": signal.signal_introduced_in_version if signal else None,
            "description": signal.description if signal else None,
            "referenced": bool(refs),
            "usages": _sorted_usages(all_usages),
            "exclusion_only": bool(refs) and all_usages == {"none"},
            "referenced_by": refs,
        })
    return rows


def item_signals(db: Session, item: models.CatalogItem) -> list[dict]:
    """The reverse direction: one item's signals, with usage and state."""
    registered = {s.name: s for s in db.query(models.SignalRegistryEntry)}
    out = []
    for name, usages in sorted(item_signal_usages(item.detection).items()):
        signal = registered.get(name)
        out.append({
            "name": name,
            "registered": signal is not None,
            "type": signal.type if signal else None,
            "category": signal.category if signal else None,
            "expected_extractor": signal.expected_extractor if signal else None,
            "state": signal.state if signal else None,
            "usages": _sorted_usages(usages),
        })
    return out
