"""Writes outbound-invocation-inventory-1.4.0.schema.json from 1.3.0.

1.4.0 (additive), 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md Part C10: will a
SOAP call still work after the move to the target .NET?
- environmentBinding, SOAP only: soap (this environment's own effective
  security: binding, mode, credential type, declared or the binding's
  default), runtimeVerdict / runtimeReasons / runtimeMatrixEntry (does the
  target's WCF client support it, from the WCF client support matrix).
- invocation, SOAP only: runtimeCompatibility (target, matrix version, the
  worst environment's verdict and the reasons).
- root: wcfClientSupport (the matrix version, target, sha256 and how many
  entries no person has confirmed yet); summary.countByRuntimeVerdict.
The platform verdict (linuxVerdict) is unchanged in shape.
Run from this folder:  python make_outbound_schema_1_4_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
schema = json.loads((HERE / "outbound-invocation-inventory-1.3.0.schema.json").read_text(encoding="utf-8"))

schema["$id"] = schema["$id"].replace("1.3.0", "1.4.0")
schema["title"] = schema["title"].replace("1.3.0", "1.4.0")
schema["properties"]["artifactVersion"] = {"const": "1.4.0"}

text = {"type": "string"}
runtime_verdict = {"enum": ["supported", "supported_with_caveat", "unsupported", "unknown"]}
defs = schema["$defs"]

defs["soapSecurity"] = {
    "type": "object", "additionalProperties": False,
    "required": ["binding", "securityMode", "clientCredentialType", "securitySource"],
    "properties": {
        "binding": text,
        "securityMode": {"type": ["string", "null"]},
        "clientCredentialType": {"type": ["string", "null"]},
        "securitySource": {"enum": ["declared", "binding_default", "unresolved"]},
    },
}
defs["runtimeCompatibility"] = {
    "type": "object", "additionalProperties": False,
    "required": ["target", "matrixVersion", "verdict", "reasons"],
    "properties": {"target": text, "matrixVersion": text, "verdict": runtime_verdict,
                   "reasons": {"type": "array", "items": text}},
}

binding = defs["environmentBinding"]["properties"]
binding["soap"] = {"$ref": "#/$defs/soapSecurity"}
binding["runtimeVerdict"] = runtime_verdict
binding["runtimeReasons"] = {"type": "array", "items": text}
binding["runtimeMatrixEntry"] = text

defs["invocation"]["properties"]["runtimeCompatibility"] = {"$ref": "#/$defs/runtimeCompatibility"}

schema["properties"]["wcfClientSupport"] = {
    "oneOf": [
        {"type": "null"},
        {"type": "object", "additionalProperties": False,
         "required": ["matrixVersion", "target", "sha256", "unconfirmedEntries"],
         "properties": {"matrixVersion": text, "target": text, "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                        "unconfirmedEntries": {"type": "integer", "minimum": 0}}},
    ],
}
summary = schema["properties"]["summary"]
summary["properties"]["countByRuntimeVerdict"] = {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}}
summary["required"] = [*summary["required"], "countByRuntimeVerdict"]

out = HERE / "outbound-invocation-inventory-1.4.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
