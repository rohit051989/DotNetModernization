"""Writes dependency-assessment-1.2.0.schema.json from 1.1.0.

1.2.0: transitive API. An upgrade that moves a dependency across a major
version (Swashbuckle 10 pulls Microsoft.OpenApi from 1.x to 2.x) has that
dependency diffed too, and a meta-package — no assemblies of its own, a props
file and dependencies (Swashbuckle.AspNetCore) — is diffed through the
packages that carry its API. So upgrade_breaking is no longer confined to
runtime packages: a package of another kind can break through what it
carries, but only on the evidence of an API diff and a call site, never by
semver. The artifact's shape is unchanged; this relaxes one rule and adds
that one. dependency-assessment-1.1.0.schema.json is kept as written.
Run from this folder:  python make_dependency_schema_1_2_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
schema = json.loads((HERE / "dependency-assessment-1.1.0.schema.json").read_text(encoding="utf-8-sig"))

schema["$id"] = schema["$id"].replace("1.1.0", "1.2.0")
schema["title"] = schema["title"].replace("1.1.0", "1.2.0")
schema["properties"]["artifactVersion"] = {"const": "1.2.0"}

package = schema["$defs"]["package"]
breaking_rule = next(rule for rule in package["allOf"]
                     if rule["if"]["properties"].get("outcome", {}).get("const") == "upgrade_breaking")
del breaking_rule["then"]["properties"]["packageKind"]   # 1.1.0: runtime or null only

package["allOf"].append({
    # Breaking without assemblies of its own: only through an API diff of what it carries, with a call site.
    "if": {"required": ["outcome", "packageKind"],
           "properties": {"outcome": {"const": "upgrade_breaking"},
                          "packageKind": {"enum": ["build", "tools", "analyzer", "content"]}}},
    "then": {"properties": {"classificationMethod": {"const": "api_diff"},
                            "breakingEvidence": {"enum": ["confirmed_call_sites", "ambiguous_call_sites_only"]}}},
})

out = HERE / "dependency-assessment-1.2.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
