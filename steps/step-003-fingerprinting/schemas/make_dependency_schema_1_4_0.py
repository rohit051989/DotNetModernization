"""Writes dependency-assessment-1.4.0.schema.json from 1.3.0.

1.4.0: framework-provided packages and the retarget signal. A package the target framework's shared framework
provides (shared-frameworks-1.0.0.json, from the SDK's PackageOverrides.txt) is outcome `framework_provided`: a
removal, not an upgrade — Microsoft.AspNetCore.Server.Kestrel 2.x in a Web SDK project, System.Text.Json on net10.0.
It carries no recommended version and emits PACKAGE_PROVIDED_BY_FRAMEWORK. The step also emits
TARGET_FRAMEWORK_BELOW_ENGAGEMENT_TARGET per project; signals are not described by this schema beyond their shape.
dependency-assessment-1.3.0.schema.json is kept as written.
Run from this folder:  python make_dependency_schema_1_4_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
schema = json.loads((HERE / "dependency-assessment-1.3.0.schema.json").read_text(encoding="utf-8-sig"))

schema["$id"] = schema["$id"].replace("1.3.0", "1.4.0")
schema["title"] = schema["title"].replace("1.3.0", "1.4.0")
schema["properties"]["artifactVersion"] = {"const": "1.4.0"}

schema["$defs"]["outcome"]["enum"].append("framework_provided")
schema["properties"]["summary"]["properties"]["countByOutcome"]["properties"]["framework_provided"] = {"type": "integer", "minimum": 0}
schema["$defs"]["package"]["allOf"].append({
    # A removal says why, and is never an upgrade: nothing to recommend, no API diff.
    "if": {"required": ["outcome"], "properties": {"outcome": {"const": "framework_provided"}}},
    "then": {"required": ["outcomeReason"], "properties": {"outcomeReason": {"type": "string", "minLength": 1}}},
})

out = HERE / "dependency-assessment-1.4.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
