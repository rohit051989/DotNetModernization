"""Writes dependency-assessment-1.8.0.schema.json from 1.7.0.

1.8.0 (additive, 39-ARTIFACTORY.md): a feed listed on the engagement's Artifactory tab is recorded as declared in
`engagement`. 1.7.0 allowed only the five NuGet.config origins, so a scan of an engagement that lists an artifactory
wrote output its own schema refused. dependency-assessment-1.7.0.schema.json is kept as written.
Run from this folder:  python make_dependency_schema_1_8_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
schema = json.loads((HERE / "dependency-assessment-1.7.0.schema.json").read_text(encoding="utf-8-sig"))

schema["$id"] = schema["$id"].replace("1.7.0", "1.8.0")
schema["title"] = schema["title"].replace("1.7.0", "1.8.0")
schema["properties"]["artifactVersion"] = {"const": "1.8.0"}
schema["$defs"]["feed"]["properties"]["declaredIn"] = {
    "enum": ["repository", "parent", "user", "machine", "default", "engagement"]}

out = HERE / "dependency-assessment-1.8.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
