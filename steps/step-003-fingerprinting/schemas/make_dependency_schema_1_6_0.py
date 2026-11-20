"""Writes dependency-assessment-1.6.0.schema.json from 1.5.0.

1.6.0 (additive, 30-DEPENDENCY-ASSESSMENT.md): a feed found in a NuGet.config in a folder above the repository is
recorded as declared in `parent`. 1.6.0 was first written by hand; this script reproduces the committed file, so every
version from 1.1.0 on has a generator. dependency-assessment-1.5.0.schema.json is kept as written.
Run from this folder:  python make_dependency_schema_1_6_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
schema = json.loads((HERE / "dependency-assessment-1.5.0.schema.json").read_text(encoding="utf-8-sig"))

schema["$id"] = schema["$id"].replace("1.5.0", "1.6.0")
schema["title"] = schema["title"].replace("1.5.0", "1.6.0")
schema["properties"]["artifactVersion"] = {"const": "1.6.0"}
schema["$defs"]["feed"]["properties"]["declaredIn"] = {"enum": ["repository", "parent", "user", "machine", "default"]}

out = HERE / "dependency-assessment-1.6.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
