r"""Writes shared-frameworks-1.0.0.json: for each target framework, the packages its shared frameworks provide.

dependency-assessment 1.4.0 (30-DEPENDENCY-ASSESSMENT Part C2): a package the target's shared framework provides
(Microsoft.AspNetCore.Server.Kestrel 2.x, System.Text.Json) is a removal, not an upgrade. The data is the SDK's own:
each targeting pack's data/PackageOverrides.txt ("PackageId|MaxVersion"), the list .NET's package pruning uses.
Committed, so the answer does not depend on which SDKs a machine has installed.
Run from this folder:  python make_shared_frameworks_1_0_0.py ["C:\Program Files\dotnet\packs"]
"""
import json
import sys
from pathlib import Path

PACKS = Path(sys.argv[1] if len(sys.argv) > 1 else r"C:\Program Files\dotnet\packs")
FRAMEWORKS = ("Microsoft.NETCore.App", "Microsoft.AspNetCore.App")


def version_key(text: str) -> tuple:
    return tuple(int(p) for p in text.split("-")[0].split("."))


out = {"version": "1.0.0", "source": "targeting packs' data/PackageOverrides.txt", "packs": {}, "frameworks": {}}
for framework in FRAMEWORKS:
    for pack in sorted((PACKS / f"{framework}.Ref").iterdir(), key=lambda p: version_key(p.name)):
        overrides = pack / "data" / "PackageOverrides.txt"
        if not overrides.exists():
            continue
        major, minor = pack.name.split(".")[:2]
        tfm = f"net{major}.{minor}"
        entries = {}
        for line in overrides.read_text(encoding="utf-8-sig").splitlines():
            if "|" in line:
                package, version = line.strip().split("|", 1)
                entries[package] = version
        out["frameworks"].setdefault(tfm, {})[framework] = dict(sorted(entries.items(), key=lambda e: e[0].lower()))
        out["packs"].setdefault(tfm, {})[framework] = pack.name

out["frameworks"] = dict(sorted(out["frameworks"].items(), key=lambda e: version_key(e[0][3:])))
target = Path(__file__).parent / "shared-frameworks-1.0.0.json"
target.write_text(json.dumps(out, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {target.name}: " + ", ".join(f"{t} ({sum(len(v) for v in f.values())})" for t, f in out["frameworks"].items()))
