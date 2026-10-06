"""Writes outbound-invocation-inventory-1.2.0.schema.json from 1.1.0.

1.2.0 (additive): every invocation carries `operations` — what the client
invokes, each with its own call site: the SOAP operation called on the proxy
or channel, the HTTP verb and path of each request, the gRPC method called on
the stub. Unresolvable ones are recorded as unresolved with the reason. Used
by step 11 to build operation-level integration edges.
Run from this folder:  python make_outbound_schema_1_2_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
schema = json.loads((HERE / "outbound-invocation-inventory-1.1.0.schema.json").read_text(encoding="utf-8"))

schema["$id"] = schema["$id"].replace("1.1.0", "1.2.0")
schema["title"] = schema["title"].replace("1.1.0", "1.2.0")
schema["properties"]["artifactVersion"] = {"const": "1.2.0"}

nullable_text = {"type": ["string", "null"]}
schema["$defs"]["invokedOperation"] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["operation", "verb", "path", "member", "resolution", "reason", "callSite"],
    "properties": {
        "operation": {**nullable_text, "description": "SOAP: the method called on the proxy or channel. gRPC: the RPC. Null for HTTP and when unresolved."},
        "verb": {"enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", None], "description": "HTTP only."},
        "path": {**nullable_text, "description": "HTTP only: the request path, base-address path prefixed; unread parts written {…}."},
        "member": {**nullable_text, "description": "The member invoked, as written."},
        "resolution": {"enum": ["resolved", "partial", "unresolved"]},
        "reason": {**nullable_text, "description": "Why unresolved, or how an indirect call was found."},
        "callSite": {"$ref": "#/$defs/callSite"},
    },
    "allOf": [
        {"if": {"properties": {"resolution": {"const": "unresolved"}}}, "then": {"properties": {"reason": {"type": "string", "minLength": 1}}}},
    ],
}
invocation = schema["$defs"]["invocation"]
invocation["properties"]["operations"] = {"type": "array", "items": {"$ref": "#/$defs/invokedOperation"}}
invocation["required"] = [*invocation["required"], "operations"]

out = HERE / "outbound-invocation-inventory-1.2.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
