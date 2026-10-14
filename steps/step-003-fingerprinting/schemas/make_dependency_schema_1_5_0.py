"""Writes dependency-assessment-1.5.0.schema.json from 1.4.0.

1.5.0: no recommended version carries a known advisory. A vulnerability names the version that fixes it
(`fixedIn`), or null when no release without a known advisory supports the target yet. A retired package's
replacement is given a version (`replacementVersion`): the replacement's newest release within the publisher's range
that supports the target, carries no known advisory and is not deprecated. dependency-assessment-1.4.0.schema.json is
kept as written.
Run from this folder:  python make_dependency_schema_1_5_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
schema = json.loads((HERE / "dependency-assessment-1.4.0.schema.json").read_text(encoding="utf-8-sig"))

schema["$id"] = schema["$id"].replace("1.4.0", "1.5.0")
schema["title"] = schema["title"].replace("1.4.0", "1.5.0")
schema["properties"]["artifactVersion"] = {"const": "1.5.0"}
schema["$defs"]["deprecation"]["properties"]["replacementVersion"] = {"type": ["string", "null"]}
schema["$defs"]["vulnerability"]["properties"]["fixedIn"] = {"type": ["string", "null"]}

out = HERE / "dependency-assessment-1.5.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
