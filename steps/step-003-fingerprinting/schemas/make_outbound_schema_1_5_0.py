"""Writes outbound-invocation-inventory-1.5.0.schema.json from 1.4.0.

1.5.0 (additive), 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md C10: a SOAP
client's platform verdict comes from the WCF client platform matrix
(wcf-client-platform-*.json), keyed by binding, effective security mode and
credential type, instead of a flat rule in code.
- environmentBinding: platformMatrixEntry, the entry the Linux verdict rests on.
- wcfClientSupport: platformMatrixVersion and platformSha256.
Run from this folder:  python make_outbound_schema_1_5_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
schema = json.loads((HERE / "outbound-invocation-inventory-1.4.0.schema.json").read_text(encoding="utf-8"))

schema["$id"] = schema["$id"].replace("1.4.0", "1.5.0")
schema["title"] = schema["title"].replace("1.4.0", "1.5.0")
schema["properties"]["artifactVersion"] = {"const": "1.5.0"}

schema["$defs"]["environmentBinding"]["properties"]["platformMatrixEntry"] = {"type": "string"}
stamp = next(o for o in schema["properties"]["wcfClientSupport"]["oneOf"] if o.get("type") == "object")
stamp["properties"]["platformMatrixVersion"] = {"type": ["string", "null"]}
stamp["properties"]["platformSha256"] = {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"}

out = HERE / "outbound-invocation-inventory-1.5.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
