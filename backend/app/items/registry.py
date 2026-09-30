"""Signal registry in the database — 28-ITEM-AND-CONVERSION-MODEL.md Part C.

Step 3 ships its registry as versioned files
(steps/step-003-fingerprinting/schemas/signal-registry-X.Y.Z.json). This
module mirrors them into `signal_registry_entries` so each signal can carry
the computed `state`/`state_reason` and a `signal_introduced_in_version`,
and so readiness can be recomputed in the same transaction as the write that
changed it.

`signal_introduced_in_version` is derived, not typed: the lowest registry
file version in which the signal name appears. For a signal registered ahead
of its extractor (never in any file yet) the caller supplies the registry
version it is expected to ship in.

Callers own the transaction: nothing here commits.
"""

import json
import re

from sqlalchemy.orm import Session

from app import catalog_rules, models
from app.items import readiness

_REGISTRY_FILENAME_RE = re.compile(r"^signal-registry-(\d+)\.(\d+)\.(\d+)\.json$")


def version_key(version: str) -> tuple[int, ...]:
    """Semver-ish sort key for registry versions ('1.10.0' > '1.9.0')."""
    return tuple(int(part) for part in version.split("."))


def _registry_files() -> list[tuple[tuple[int, ...], dict]]:
    files = []
    for path in catalog_rules._registry_dir().glob("signal-registry-*.json"):
        match = _REGISTRY_FILENAME_RE.match(path.name)
        if match:
            files.append(
                (tuple(int(part) for part in match.groups()), json.loads(path.read_text(encoding="utf-8")))
            )
    if not files:
        raise FileNotFoundError(f"No signal-registry-*.json found under {catalog_rules._registry_dir()}")
    files.sort(key=lambda entry: entry[0])
    return files


def upsert_extractor(db: Session, data: dict) -> tuple[models.Extractor, bool]:
    extractor = db.get(models.Extractor, data["name"])
    created = extractor is None
    if extractor is None:
        extractor = models.Extractor(name=data["name"])
        db.add(extractor)
    extractor.description = data.get("description")
    extractor.status = data["status"]
    # Sorted and de-duplicated so the declaration is stable to diff.
    extractor.emits = sorted(set(data.get("emits", [])))
    extractor.planned_emits = sorted(set(data.get("planned_emits", [])))
    extractor.owner_team = data.get("owner_team")
    extractor.updated_at = readiness._now()
    return extractor, created


def upsert_signal(db: Session, data: dict, introduced_in: str) -> tuple[models.SignalRegistryEntry, bool]:
    signal = db.get(models.SignalRegistryEntry, data["name"])
    created = signal is None
    if signal is None:
        signal = models.SignalRegistryEntry(name=data["name"])
        db.add(signal)
    signal.category = data["category"]
    signal.type = data["type"]
    signal.description = data.get("description")
    signal.expected_extractor = data["extractor"]
    signal.evidence_kind = data["evidence_kind"]
    signal.value_semantics = data.get("value_semantics")
    signal.signal_introduced_in_version = introduced_in
    signal.updated_at = readiness._now()
    return signal, created


def sync_from_registry_files(
    db: Session, extractor_declarations: list[dict], anticipated: list[dict] | None = None
) -> dict:
    """Upserts the extractor declarations, then every signal in the
    highest-versioned registry file, then `anticipated` signals (registered
    ahead of their extraction code) that no registry file carries yet —
    once a file does, the file wins. Then enforces the claim rule and
    recomputes readiness. Raises (422) without writing anything durable if
    any registered signal ends up unclaimed; the caller's rollback discards
    the partial upserts.

    Signals already in the table but in neither source (registered through
    the API) are left alone."""
    for data in extractor_declarations:
        upsert_extractor(db, data)
    db.flush()

    files = _registry_files()
    introduced: dict[str, str] = {}
    for _key, registry in files:
        for signal in registry["signals"]:
            introduced.setdefault(signal["name"], registry["registry_version"])

    latest = files[-1][1]
    # Checked before any signal row is written: a registry signal naming an
    # undeclared extractor must fail as unclaimed, not as a foreign key.
    readiness.assert_claimed(db, [(signal["name"], signal["extractor"]) for signal in latest["signals"]])
    created = 0
    for signal in latest["signals"]:
        _row, was_created = upsert_signal(db, signal, introduced[signal["name"]])
        created += was_created

    pending = [signal for signal in (anticipated or []) if signal["name"] not in introduced]
    readiness.assert_claimed(db, [(signal["name"], signal["extractor"]) for signal in pending])
    for signal in pending:
        _row, was_created = upsert_signal(db, signal, signal["signal_introduced_in_version"])
        created += was_created

    readiness.assert_all_signals_claimed(db)
    touched = {s["name"] for s in latest["signals"]} | {s["name"] for s in pending}
    # Names a planned declaration covers but nobody registered yet can still
    # unblock or re-point items waiting on them.
    for extractor in db.query(models.Extractor):
        touched |= set(extractor.emits) | set(extractor.planned_emits)
    propagation = readiness.refresh_readiness(db, touched_signals=touched)
    return {
        "registry_version": latest["registry_version"],
        "signals_in_registry": len(latest["signals"]),
        "signals_anticipated": len(pending),
        "signals_created": created,
        "extractors": len(extractor_declarations),
        **propagation,
    }
