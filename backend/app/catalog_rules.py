"""Step 4 catalog schema support (24-STEP-004-CLASSIFICATION.md Parts B and C).

Everything here is write-time validation and bookkeeping for the catalog
schema migration (J1). No classification logic lives here — the engine that
evaluates these rules against a fingerprint is step 4's own codebase (J3),
not the platform backend.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.errors import errors

_REGISTRY_FILENAME_RE = re.compile(r"^signal-registry-(\d+)\.(\d+)\.(\d+)\.json$")


def _registry_dir() -> Path:
    return Path(settings.platform_root) / "steps" / "step-003-fingerprinting" / "schemas"


def _latest_registry_path() -> Path:
    candidates = []
    for path in _registry_dir().glob("signal-registry-*.json"):
        match = _REGISTRY_FILENAME_RE.match(path.name)
        if match:
            candidates.append((tuple(int(part) for part in match.groups()), path))
    if not candidates:
        raise FileNotFoundError(f"No signal-registry-*.json found under {_registry_dir()}")
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


@lru_cache(maxsize=1)
def _load_active_registry_file() -> dict:
    """The active registry is the highest-versioned signal-registry-*.json
    file step 3 ships. Cached for the process lifetime — this is a
    single-machine, single-operator build (CLAUDE.md's operating model);
    restart the backend after a new registry version lands."""
    path = _latest_registry_path()
    return json.loads(path.read_text(encoding="utf-8"))


def registered_signal_names() -> frozenset[str]:
    return frozenset(signal["name"] for signal in _load_active_registry_file()["signals"])


def registry_version() -> str:
    return _load_active_registry_file()["registry_version"]


# Part C 'Signal condition fields' / §7 — signals that must not be a
# pattern's only anchor. A fixed, documented list, not a registry property.
WEAK_ANCHOR_SIGNALS = frozenset(
    {"PROGRAM_CS_FILE", "SERVICES_FOLDER", "MICROSOFT_ASPNETCORE_NAMESPACE", "CONNECTION_STRING_CONFIG"}
)


def registered_signals_full() -> list[dict]:
    """Every registered signal with its description, for the rule builder's
    signal selects (Part B4: 'Every signal select shows its registry
    description') and the anchor-signal weak-signal warning."""
    return [
        {**signal, "weak_anchor": signal["name"] in WEAK_ANCHOR_SIGNALS}
        for signal in _load_active_registry_file()["signals"]
    ]



# ---------- Rule id assignment (Part C 'Rule ids') ----------


def _assign_ids(conditions: list[dict], prefix: str) -> None:
    for index, condition in enumerate(conditions):
        if not condition.get("id"):
            condition["id"] = f"{prefix}[{index}]"


def assign_positional_rule_ids(ruleset: dict) -> dict:
    """Fills in a positional fallback id (e.g. 'all[0]') for any condition
    that omitted one. Mutates and returns the same dict. Ids are only
    required in the sense that they always end up populated — omission is
    never rejected, just backfilled, per Part C."""
    _assign_ids(ruleset.get("all", []), "all")
    _assign_ids(ruleset.get("any", []), "any")
    _assign_ids(ruleset.get("supporting", []), "supporting")
    _assign_ids(ruleset.get("none", []), "none")
    _assign_ids(ruleset.get("metadata", []), "metadata")
    for group_index, group in enumerate(ruleset.get("atLeast", [])):
        if not group.get("id"):
            group["id"] = f"atLeast[{group_index}]"
        _assign_ids(group.get("of", []), f"atLeast[{group_index}].of")
    return ruleset


def _all_rule_ids(ruleset: dict) -> list[str]:
    ids = [c["id"] for c in ruleset.get("all", []) if c.get("id")]
    ids += [c["id"] for c in ruleset.get("any", []) if c.get("id")]
    ids += [c["id"] for c in ruleset.get("supporting", []) if c.get("id")]
    ids += [c["id"] for c in ruleset.get("none", []) if c.get("id")]
    ids += [c["id"] for c in ruleset.get("metadata", []) if c.get("id")]
    for group in ruleset.get("atLeast", []):
        if group.get("id"):
            ids.append(group["id"])
        ids += [c["id"] for c in group.get("of", []) if c.get("id")]
    return ids


def validate_rule_ids_unique(ruleset: dict) -> None:
    ids = _all_rule_ids(ruleset)
    seen: set[str] = set()
    for rule_id in ids:
        if rule_id in seen:
            raise errors(
                422,
                [
                    {
                        "field": "detection_rules",
                        "message": f"Rule id '{rule_id}' is used more than once; ids must be unique within a pattern.",
                        "code": "DUPLICATE_RULE_ID",
                    }
                ],
            )
        seen.add(rule_id)


# ---------- Signal reference extraction and B3 validation ----------


def _referenced_signal_names(ruleset: dict, anchor_signals: list[str]) -> set[str]:
    names: set[str] = set(anchor_signals)
    for condition in ruleset.get("all", []):
        names.add(condition["signal"]["name"])
    for condition in ruleset.get("any", []):
        names.add(condition["signal"]["name"])
    for condition in ruleset.get("supporting", []):
        names.add(condition["signal"]["name"])
    for condition in ruleset.get("none", []):
        names.add(condition["signal"]["name"])
    for group in ruleset.get("atLeast", []):
        for condition in group.get("of", []):
            names.add(condition["signal"]["name"])
    return names


def validate_signal_references(
    ruleset: dict, anchor_signals: list[str], rules_status: str, required_signals_pending: list[dict]
) -> list[str]:
    """Part B3. Returns non-fatal warnings (only ever populated for
    'draft'); raises a 422 naming the offending signal(s) otherwise."""
    referenced = _referenced_signal_names(ruleset, anchor_signals)
    registered = registered_signal_names()
    unknown = sorted(referenced - registered)
    if not unknown:
        return []

    if rules_status == "active":
        raise errors(
            422,
            [
                {
                    "field": "detection_rules",
                    "message": f"Signal '{name}' is not in the active registry ({registry_version()}).",
                    "code": "UNREGISTERED_SIGNAL",
                }
                for name in unknown
            ],
        )

    if rules_status == "awaiting_signals":
        declared = {entry["signal_name"] for entry in required_signals_pending}
        undeclared = sorted(set(unknown) - declared)
        if undeclared:
            raise errors(
                422,
                [
                    {
                        "field": "required_signals_pending",
                        "message": f"Signal '{name}' is not registered and is not declared in required_signals_pending.",
                        "code": "UNDECLARED_SIGNAL",
                    }
                    for name in undeclared
                ],
            )
        return []

    # draft: permitted, warned rather than rejected.
    return [f"Signal '{name}' is not yet registered." for name in unknown]


def validate_compatibility(db: Session, compatible_with: list[str], conflicts_with: list[str]) -> None:
    """Part B1: a pattern must not appear in both lists, and every
    referenced id must exist."""
    overlap = sorted(set(compatible_with) & set(conflicts_with))
    if overlap:
        raise errors(
            422,
            [
                {
                    "field": "conflicts_with",
                    "message": f"Pattern '{other_id}' appears in both compatible_with and conflicts_with.",
                    "code": "COMPATIBLE_AND_CONFLICTING",
                }
                for other_id in overlap
            ],
        )

    referenced_ids = sorted(set(compatible_with) | set(conflicts_with))
    if not referenced_ids:
        return
    existing = {
        row[0]
        for row in db.query(models.Pattern.id).filter(models.Pattern.id.in_(referenced_ids)).all()
    }
    missing = sorted(set(referenced_ids) - existing)
    if missing:
        raise errors(
            422,
            [
                {
                    "field": "compatible_with",
                    "message": f"Pattern '{other_id}' does not exist.",
                    "code": "UNKNOWN_PATTERN_ID",
                }
                for other_id in missing
            ],
        )


# ---------- Catalog revision (Part H) ----------


def bump_catalog_revision(db: Session, entity_type: str, entity_id: str, operation: str) -> None:
    db.add(models.CatalogRevision(entity_type=entity_type, entity_id=entity_id, operation=operation))


def current_catalog_revision(db: Session) -> int:
    return db.query(func.max(models.CatalogRevision.id)).scalar() or 0


# ---------- Promotion reporting (Part B3: re-validation on new signal registration) ----------


def pending_signal_promotions(db: Session) -> list[dict]:
    """For every non-deleted 'awaiting_signals' pattern, reports which
    blocking pending signals are still missing from the active registry.
    An empty `still_missing_blocking` means the pattern is promotable —
    promotion itself stays a human action (Part B3)."""
    registered = registered_signal_names()
    patterns = (
        db.query(models.Pattern)
        .filter(models.Pattern.rules_status == "awaiting_signals", models.Pattern.deleted_at.is_(None))
        .order_by(models.Pattern.id)
        .all()
    )
    report = []
    for pattern in patterns:
        pending = pattern.required_signals_pending or []
        still_missing_blocking = sorted(
            entry["signal_name"]
            for entry in pending
            if entry.get("blocking", True) and entry["signal_name"] not in registered
        )
        report.append(
            {
                "pattern_id": pattern.id,
                "name": pattern.name,
                "required_signals_pending": pending,
                "still_missing_blocking": still_missing_blocking,
                "promotable": len(still_missing_blocking) == 0,
            }
        )
    return report


# ---------- RULE_REFERENCES_NEVER_EMITTED_SIGNAL (governance observation) ----------


def never_emitted_signal_findings(db: Session, engagement_id: str) -> list[dict]:
    """For every active pattern, flags any signal its rules reference that
    has never appeared in a fingerprint anywhere in this engagement — across
    every repository, not just one. Without this, a pattern whose rule can
    never fire because it references the wrong signal name (a broken rule)
    looks identical to a pattern that correctly finds no matching evidence
    because this engagement genuinely has no code of that shape ("no legacy
    code in the sample"). Both currently just accumulate in
    never_matched_pattern_ids; this is what tells them apart."""
    emitted = {
        row[0]
        for row in db.query(models.FingerprintSignal.signal_name)
        .join(models.Repository, models.Repository.id == models.FingerprintSignal.repository_id)
        .filter(models.Repository.engagement_id == engagement_id, models.Repository.deleted_at.is_(None))
        .distinct()
    }

    findings = []
    patterns = (
        db.query(models.Pattern)
        .filter(models.Pattern.rules_status == "active", models.Pattern.deleted_at.is_(None))
        .order_by(models.Pattern.id)
        .all()
    )
    for pattern in patterns:
        referenced = _referenced_signal_names(pattern.detection_rules, pattern.anchor_signals or [])
        never_emitted = sorted(referenced - emitted)
        if never_emitted:
            findings.append(
                {
                    "pattern_id": pattern.id,
                    "name": pattern.name,
                    "never_emitted_signals": never_emitted,
                }
            )
    return findings
