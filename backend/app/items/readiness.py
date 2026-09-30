"""Two-state readiness — 28-ITEM-AND-CONVERSION-MODEL.md Part C.

A signal is `ready` when its expected extractor is `implemented` and lists
the signal in `emits`. An item is `ready` when its detection is satisfiable
(it references at least one signal or step 2 metadata condition) and every
signal it references is `ready`. Both states are computed here and nowhere
else; no API accepts them as input.

**A registered signal that no extractor claims is a hard error.** "Claims"
means the signal's `expected_extractor` exists and lists the signal in
`emits` or `planned_emits`. A planned claim is still a claim: the signal is
legitimately `not_ready` / `extractor_not_implemented`, which is how a
signal is registered ahead of its extraction code without being forgotten —
either on a `planned` extractor, or in an `implemented` extractor's
`planned_emits` when the signal belongs to an extractor that already ships.
What is never allowed is a signal nobody has declared at all, so every write
that could produce one (registry sync, signal registration, an extractor
declaration dropping a signal) checks claims before committing.

Callers own the transaction: nothing here commits.
"""

import datetime

from sqlalchemy.orm import Session

from app import models
from app.errors import errors
from app.items.detection import referenced_signal_names


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# ---------- claims (the hard error) ----------


def unclaimed_signals(claims: list[tuple[str, str]], extractors: dict[str, models.Extractor]) -> list[dict]:
    """`claims` is (signal name, expected extractor) pairs. Returns one
    SIGNAL_UNCLAIMED problem per pair whose extractor is missing or does not
    list the signal in `emits` or `planned_emits`. Callers check *before* writing a signal, so
    a missing extractor is reported as this, not as a foreign-key failure."""
    problems = []
    for signal_name, extractor_name in claims:
        extractor = extractors.get(extractor_name)
        if extractor is None:
            problems.append(
                {
                    "field": "expected_extractor",
                    "message": f"Signal '{signal_name}' expects extractor '{extractor_name}', which is not registered.",
                    "code": "SIGNAL_UNCLAIMED",
                }
            )
        elif signal_name not in extractor.emits and signal_name not in extractor.planned_emits:
            problems.append(
                {
                    "field": "emits",
                    "message": f"Signal '{signal_name}' expects extractor '{extractor_name}', whose declaration lists it in neither emits nor planned_emits.",
                    "code": "SIGNAL_UNCLAIMED",
                }
            )
    return problems


def assert_claimed(db: Session, claims: list[tuple[str, str]]) -> None:
    """Raises a 422 naming every pair in `claims` no extractor claims."""
    db.flush()
    extractors = {e.name: e for e in db.query(models.Extractor).all()}
    problems = unclaimed_signals(claims, extractors)
    if problems:
        raise errors(422, problems)


def assert_all_signals_claimed(db: Session) -> None:
    """Raises a 422 naming every registered signal no extractor claims."""
    db.flush()
    rows = db.query(models.SignalRegistryEntry).order_by(models.SignalRegistryEntry.name).all()
    assert_claimed(db, [(row.name, row.expected_extractor) for row in rows])


# ---------- state computation ----------


def signal_state(
    signal: models.SignalRegistryEntry, extractors: dict[str, models.Extractor]
) -> tuple[str, dict | None]:
    extractor = extractors.get(signal.expected_extractor)
    if extractor is not None and extractor.status == "implemented" and signal.name in extractor.emits:
        return "ready", None
    # Either the extractor is `planned`, or it ships but lists this signal
    # only in `planned_emits`. Both mean the extraction code does not exist.
    return "not_ready", {
        "state": "not_ready",
        "reason_code": "extractor_not_implemented",
        "expected_extractor": signal.expected_extractor,
    }


def item_state(
    detection: dict,
    signals: dict[str, models.SignalRegistryEntry],
    declared_by: dict[str, str],
) -> tuple[str, dict | None]:
    """`declared_by` maps a signal name to the extractor declaring it, for
    signals not registered yet, so a blocking entry can still name the
    extractor that would unblock it."""
    referenced = sorted(referenced_signal_names(detection))
    # Step 2 metadata conditions count as mapped: step 2 always runs, so an
    # item detected purely by project metadata (e.g. structuralType) is
    # satisfiable and ready. Only an item with nothing to match is pending.
    has_metadata = bool(detection.get("match", {}).get("metadata"))
    if not referenced and not has_metadata:
        return "not_ready", {
            "state": "not_ready",
            "reason_code": "signal_mapping_pending",
            "blocking_signals": [],
        }

    blocking = []
    for name in referenced:
        signal = signals.get(name)
        if signal is None:
            # Not a Part C signal reason code: the signal doesn't exist to
            # have a state. Kept distinct so the backlog can tell "build this
            # extractor" from "register this signal first".
            blocking.append(
                {"signal": name, "reason_code": "signal_not_registered", "expected_extractor": declared_by.get(name)}
            )
        elif signal.state != "ready":
            blocking.append(
                {
                    "signal": name,
                    "reason_code": "extractor_not_implemented",
                    "expected_extractor": signal.expected_extractor,
                }
            )

    if not blocking:
        return "ready", None
    return "not_ready", {"state": "not_ready", "reason_code": "signal_not_ready", "blocking_signals": blocking}


# ---------- propagation ----------


def _declared_by(extractors: dict[str, models.Extractor]) -> dict[str, str]:
    """First extractor (by name) declaring each signal name, in `emits` or
    `planned_emits`."""
    result: dict[str, str] = {}
    for name in sorted(extractors):
        for signal_name in [*extractors[name].emits, *extractors[name].planned_emits]:
            result.setdefault(signal_name, name)
    return result


def recompute_item(db: Session, item: models.CatalogItem) -> bool:
    """Recomputes one item in place. Returns True if its state changed."""
    signals = {s.name: s for s in db.query(models.SignalRegistryEntry).all()}
    extractors = {e.name: e for e in db.query(models.Extractor).all()}
    state, reason = item_state(item.detection, signals, _declared_by(extractors))
    changed = state != item.state
    item.state = state
    item.state_reason = reason
    return changed


def refresh_readiness(db: Session, touched_signals: set[str] | None = None) -> dict:
    """Recomputes every signal's state, then every item whose detection
    references a signal that changed state — or that was registered or
    declared in this write (`touched_signals`), since an item blocked on an
    unregistered name can be unblocked by its registration.

    This is the only promotion path: an item becomes ready because a signal
    it depends on did, never because anyone edited the item. Returns a
    report of what moved."""
    db.flush()
    extractors = {e.name: e for e in db.query(models.Extractor).all()}
    signals = {s.name: s for s in db.query(models.SignalRegistryEntry).all()}

    changed_signals: list[dict] = []
    for name in sorted(signals):
        signal = signals[name]
        state, reason = signal_state(signal, extractors)
        if state != signal.state:
            changed_signals.append({"signal": name, "from": signal.state, "to": state})
        if state != signal.state or reason != signal.state_reason:
            signal.state = state
            signal.state_reason = reason
            signal.updated_at = _now()

    affected = {entry["signal"] for entry in changed_signals} | (touched_signals or set())
    declared_by = _declared_by(extractors)

    changed_items: list[dict] = []
    for item in db.query(models.CatalogItem).order_by(models.CatalogItem.id):
        if not affected & referenced_signal_names(item.detection):
            continue
        state, reason = item_state(item.detection, signals, declared_by)
        if state != item.state:
            changed_items.append({"item_id": item.id, "from": item.state, "to": state})
        if state != item.state or reason != item.state_reason:
            item.state = state
            item.state_reason = reason
            item.updated_at = _now()

    db.flush()
    return {"signals_changed": changed_signals, "items_changed": changed_items}
