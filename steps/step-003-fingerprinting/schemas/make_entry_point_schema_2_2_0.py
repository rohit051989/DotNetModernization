"""Writes entry-point-inventory-2.2.0.schema.json from 2.1.0.

2.2.0 (additive): each project carries `signals` — step 4 as a signal
producer (EXPOSES_WCF_SERVICE, WCF_SERVICE_HOSTING, HOSTS_WCF_SERVICE,
EXPOSES_HTTP_API, EXPOSES_ASMX_SERVICE, EXPOSES_GRPC_SERVICE,
EXPOSES_WEBFORMS_UI; signal registry 1.8.0). The signal shape is step 3's,
copied from application-fingerprint-1.2.0 so the two cannot drift.
Run from this folder:  python make_entry_point_schema_2_2_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
schema = json.loads((HERE / "entry-point-inventory-2.1.0.schema.json").read_text(encoding="utf-8"))
fingerprint = json.loads((HERE / "application-fingerprint-1.2.0.schema.json").read_text(encoding="utf-8"))

schema["$id"] = schema["$id"].replace("2.1.0", "2.2.0")
schema["title"] = schema["title"].replace("2.1.0", "2.2.0")
schema["properties"]["artifactVersion"] = {"const": "2.2.0"}

source_defs = fingerprint["$defs"]
for name in ("signalCategory", "signalType", "evidenceSourceType", "evidence", "signal", "signalEvidenceKind"):
    schema["$defs"][name] = source_defs[name]

project = schema["$defs"]["project"]
project["properties"]["signals"] = {"type": "array", "items": {"$ref": "#/$defs/signal"}}
project["required"] = [*project["required"], "signals"]

out = HERE / "entry-point-inventory-2.2.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
