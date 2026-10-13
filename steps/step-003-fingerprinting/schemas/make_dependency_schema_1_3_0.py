"""Writes dependency-assessment-1.3.0.schema.json from 1.2.0.

1.3.0: deprecation scope. NuGet deprecates versions, not packages, so a deprecated release of a maintained
package (CriticalBugs, Other, with a newer version that is not deprecated) is told apart from a retired package
(Legacy, or no newer version free of deprecation). `deprecation.scope` is `package` or `version`, and
`deprecation.newestNotDeprecated` names the release that resolves a version deprecation. Item detection raises
package-replacement-required only for a package deprecation; a version deprecation is the upgrade the outcome
already describes. Also: the public comparison feed's role, public_comparison, is now in the feed role enum
(1.2.0 omitted it, so a repository with a client feed failed validation). dependency-assessment-1.2.0.schema.json
is kept as written.
Run from this folder:  python make_dependency_schema_1_3_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
schema = json.loads((HERE / "dependency-assessment-1.2.0.schema.json").read_text(encoding="utf-8-sig"))

schema["$id"] = schema["$id"].replace("1.2.0", "1.3.0")
schema["title"] = schema["title"].replace("1.2.0", "1.3.0")
schema["properties"]["artifactVersion"] = {"const": "1.3.0"}

# A repository whose NuGet.config declares a client feed and not nuget.org is compared with nuget.org (Part B3):
# that feed is recorded with role public_comparison, declared nowhere ("default").
schema["$defs"]["feed"]["properties"]["role"]["enum"].append("public_comparison")

deprecation = schema["$defs"]["deprecation"]
deprecation["required"] += ["scope", "newestNotDeprecated"]
deprecation["properties"]["scope"] = {"enum": ["package", "version"]}
deprecation["properties"]["newestNotDeprecated"] = {"type": ["string", "null"]}
deprecation["allOf"] = [{"if": {"properties": {"scope": {"const": "version"}}},
                         "then": {"properties": {"newestNotDeprecated": {"type": "string", "minLength": 1}}}}]

out = HERE / "dependency-assessment-1.3.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
