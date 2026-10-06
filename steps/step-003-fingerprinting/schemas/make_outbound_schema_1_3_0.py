"""Writes outbound-invocation-inventory-1.3.0.schema.json from 1.2.0.

1.3.0 (additive), 29-STEPS-004-005-INVENTORIES.md Part C9:
- environmentBinding: hostProject (a class library's configuration comes from
  the host that runs it), deployParameter / linkMethod / linkConfidence (a
  value set by a Web Deploy SetParameters file, and how it was linked).
- invocation: constructionSites — where the client is created, kept apart
  from callSites, which are now where it is invoked.
- project: deployParameters (every SetParameters parameter, a value only for
  a path or a URL linked to a used endpoint) and entryPointBackend (per step 4
  entry point, the outbound call sites it reaches).
Run from this folder:  python make_outbound_schema_1_3_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
schema = json.loads((HERE / "outbound-invocation-inventory-1.2.0.schema.json").read_text(encoding="utf-8"))

schema["$id"] = schema["$id"].replace("1.2.0", "1.3.0")
schema["title"] = schema["title"].replace("1.2.0", "1.3.0")
schema["properties"]["artifactVersion"] = {"const": "1.3.0"}

text = {"type": "string"}
nullable_text = {"type": ["string", "null"]}
confidence = {"type": ["number", "null"], "minimum": 0, "maximum": 1}
defs = schema["$defs"]


def add(definition: str, properties: dict) -> None:
    defs[definition]["properties"].update(properties)
    defs[definition]["required"] = [*defs[definition]["required"], *properties]


add("environmentBinding", {
    "hostProject": nullable_text,
    "deployParameter": nullable_text,
    "linkMethod": {"enum": ["parameters_xml", "name_and_path", None]},
    "linkConfidence": confidence,
})
add("invocation", {"constructionSites": {"type": "array", "items": {"$ref": "#/$defs/callSite"}}})
add("project", {
    "deployParameters": {"type": "array", "items": {"$ref": "#/$defs/deployParameter"}},
    "entryPointBackend": {"type": "array", "items": {"$ref": "#/$defs/entryPointBackend"}},
})

defs["deployParameter"] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["projectPath", "sourceFile", "environment", "name", "kind", "line", "value", "linkedKind", "linkedName",
                 "linkMethod", "linkConfidence", "linkNote"],
    "properties": {
        "projectPath": nullable_text,
        "sourceFile": text,
        "environment": text,
        "name": text,
        "kind": {"enum": ["url", "path", "connection_string", "sensitive", "other"]},
        "line": {"type": "integer"},
        "value": {**nullable_text, "description": "Only for a path, or a URL linked to an endpoint a used invocation cites (normalised)."},
        "linkedKind": {"enum": ["client_endpoint", "app_setting", "connection_string", "xpath", None]},
        "linkedName": nullable_text,
        "linkMethod": {"enum": ["parameters_xml", "name_and_path", None]},
        "linkConfidence": confidence,
        "linkNote": nullable_text,
    },
    # Never a value for a secret, a connection string or an unclassified parameter.
    "allOf": [
        {"if": {"properties": {"kind": {"enum": ["sensitive", "connection_string", "other"]}}},
         "then": {"properties": {"value": {"type": "null"}}}},
    ],
}
defs["backendCall"] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["invocationId", "mechanism", "operation", "callSite", "depth", "via", "conditional", "inLoop", "context"],
    "properties": {
        "invocationId": text,
        "mechanism": text,
        "operation": nullable_text,
        "callSite": {"$ref": "#/$defs/callSite"},
        "depth": {"type": "integer", "minimum": 0},
        "via": {"type": "array", "items": text},
        "conditional": {"type": "boolean"},
        "inLoop": {"type": "boolean"},
        "context": {"type": "array", "items": text},
    },
}
defs["unfollowedPath"] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reason", "callSite"],
    "properties": {"reason": text, "callSite": {"$ref": "#/$defs/callSite"}},
}
defs["entryPointBackend"] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["entryPointId", "status", "calls", "unresolved"],
    "properties": {
        "entryPointId": text,
        "status": {"enum": ["yes", "no", "unresolved"]},
        "calls": {"type": "array", "items": {"$ref": "#/$defs/backendCall"}},
        "unresolved": {"type": "array", "items": {"$ref": "#/$defs/unfollowedPath"}},
    },
}

out = HERE / "outbound-invocation-inventory-1.3.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
