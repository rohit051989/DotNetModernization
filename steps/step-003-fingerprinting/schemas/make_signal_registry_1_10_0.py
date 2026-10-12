"""Writes signal-registry-1.10.0.json from 1.9.0.

1.10.0 (additive): the first framework delta signal, from EntryPointInventory
(step 4 scanner 2.3.0) — a known breaking change between a project's framework
and a later one, detected in discovery so the conversion plan fixes it before
the retarget (34-CONVERSION-ARCHITECTURE.md, "Framework deltas").
Run from this folder:  python make_signal_registry_1_10_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
registry = json.loads((HERE / "signal-registry-1.9.0.json").read_text(encoding="utf-8"))
registry["registry_version"] = "1.10.0"

registry["signals"] += [
    {
        "name": "AMBIGUOUS_TOP_LEVEL_PROGRAM_ON_NET10",
        "category": "ENTRY_POINT",
        "type": "ENTRY_POINT",
        "description": "From .NET 10, ASP.NET Core generates a public Program for a web project whose entry point is "
                       "top-level statements. A project that references two or more projects whose Program is then public, "
                       "and names Program (WebApplicationFactory<Program>), no longer compiles: CS0433. On earlier "
                       "frameworks the implicit Program is internal, so only an explicit public partial class Program "
                       "was visible. Emitted by lifecycle step 4 (entry-point-inventory) from step 2's project references "
                       "and SDKs and each project's top-level statements.",
        "extractor": "EntryPointInventory",
        "evidence_kind": "FILE",
        "value_semantics": "the file holding the top-level statements of a referenced project whose Program becomes public "
                           "only on net10.0 (where the fix goes); located at the consuming file that names Program, a line "
                           "per use. One row per such referenced project.",
    },
]

out = HERE / "signal-registry-1.10.0.json"
out.write_text(json.dumps(registry, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}: {len(registry['signals'])} signals")
