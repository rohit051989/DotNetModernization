"""Active signal registry loader. Mirrors backend/app/catalog_rules.py's
logic (which this package cannot import — see db.py's docstring) so both
sides agree on what "the active registry" means: the highest-versioned
signal-registry-*.json file step 3 ships."""

import json
import re
from pathlib import Path

_FILENAME_RE = re.compile(r"^signal-registry-(\d+)\.(\d+)\.(\d+)\.json$")


def _registry_dir(platform_root: Path) -> Path:
    return platform_root / "steps" / "step-003-fingerprinting" / "schemas"


def _active_registry_path(platform_root: Path) -> Path:
    candidates = []
    for path in _registry_dir(platform_root).glob("signal-registry-*.json"):
        match = _FILENAME_RE.match(path.name)
        if match:
            candidates.append((tuple(int(part) for part in match.groups()), path))
    if not candidates:
        raise FileNotFoundError(f"No signal-registry-*.json found under {_registry_dir(platform_root)}")
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def load_active_registry(platform_root: Path) -> tuple[str, frozenset[str]]:
    data = json.loads(_active_registry_path(platform_root).read_text(encoding="utf-8"))
    return data["registry_version"], frozenset(s["name"] for s in data["signals"])


def load_active_registry_entries(platform_root: Path) -> tuple[str, dict[str, dict]]:
    """Full entries by signal name, not just the name set — probe.py needs
    each signal's declared category/type/evidence_kind to synthesise a row
    that a condition's category/type filters will actually accept."""
    data = json.loads(_active_registry_path(platform_root).read_text(encoding="utf-8"))
    return data["registry_version"], {s["name"]: s for s in data["signals"]}
