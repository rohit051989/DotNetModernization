"""Writes signal-registry-1.15.0.json from 1.14.0.

1.15.0 (additive), the related forms of host-local time:
- DATETIME_NOW_USAGE (ApiUsageExtractor) also matches TimeZoneInfo.Local, DateTimeKind.Local and a call to
  ToLocalTime(), beside DateTime.Now, DateTime.Today and DateTimeOffset.Now. Each depends on the host's time zone.
No signal is added or removed; the entry's description and value semantics name the new values.
Run from this folder:  python make_signal_registry_1_15_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
registry = json.loads((HERE / "signal-registry-1.14.0.json").read_text(encoding="utf-8"))
registry["registry_version"] = "1.15.0"

entry = next(s for s in registry["signals"] if s["name"] == "DATETIME_NOW_USAGE")
entry["description"] = ("Access to DateTime.Now, DateTime.Today or DateTimeOffset.Now (host-local time, which is UTC in a "
                        "default Linux container), or to what depends on the host's time zone: TimeZoneInfo.Local, "
                        "DateTimeKind.Local, a call to ToLocalTime().")
entry["value_semantics"] = ("the fully qualified member (System.DateTime.Now, System.DateTime.Today, System.DateTimeOffset.Now, "
                            "System.TimeZoneInfo.Local, System.DateTimeKind.Local), or ToLocalTime for the call; one row per "
                            "distinct member per file. Syntax-only: confidence 0.9 for a type-qualified member, 0.8 for "
                            "ToLocalTime, whose receiver syntax cannot type.")

out = HERE / "signal-registry-1.15.0.json"
out.write_text(json.dumps(registry, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}: {len(registry['signals'])} signals")
