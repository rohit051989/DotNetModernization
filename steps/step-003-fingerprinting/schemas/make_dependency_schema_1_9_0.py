"""Writes dependency-assessment-1.9.0.schema.json from 1.8.0.

1.9.0 (additive, 30-DEPENDENCY-ASSESSMENT.md "Unlisted versions"): unlisted versions are looked up too. NuGet's
unlisting only hides a version from search; it still restores by exact version.
  unknownCause        adds only_unlisted: the referenced version is on no authority feed, and every version the
                      feeds hold is unlisted
  unlistedFeeds       for only_unlisted: each feed holding the package (name, normalised url, its versions, all unlisted)
  listingNote         on a package, a short note when an unlisted version is involved: the version in use is
                      unlisted, or a proposed version is unlisted because no listed one fits
  summary.feedListing per authority feed that answered: packages answered, packages it holds only unlisted, versions
                      answered and unlisted, whether nearly all are unlisted, and the note that says so
dependency-assessment-1.8.0.schema.json is kept as written.
Run from this folder:  python make_dependency_schema_1_9_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
schema = json.loads((HERE / "dependency-assessment-1.8.0.schema.json").read_text(encoding="utf-8-sig"))

schema["$id"] = schema["$id"].replace("1.8.0", "1.9.0")
schema["title"] = schema["title"].replace("1.8.0", "1.9.0")
schema["properties"]["artifactVersion"] = {"const": "1.9.0"}

NAME = {"type": "string", "minLength": 1}
URL = {"type": "string", "minLength": 1,
       "description": "Normalised: scheme, host, port, path; never userinfo, query or fragment (Part B4)."}
COUNT = {"type": "integer", "minimum": 0}
defs = schema["$defs"]
defs["unknownCause"] = {"enum": ["feed_auth", "feed_unreachable", "not_on_feed", "version_unresolved", "only_unlisted"]}
defs["unlistedFeed"] = {
    "type": "object", "additionalProperties": False,
    "required": ["name", "url", "versions"],
    "properties": {
        "name": NAME, "url": URL,
        "versions": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1},
                     "description": "Every version the feed holds, all unlisted, newest first."},
    },
}
defs["feedListing"] = {
    "type": "object", "additionalProperties": False,
    "required": ["name", "url", "packagesAnswered", "packagesOnlyUnlisted", "versionsAnswered", "versionsUnlisted",
                 "mostlyUnlisted"],
    "properties": {
        "name": NAME, "url": URL,
        "packagesAnswered": COUNT, "packagesOnlyUnlisted": COUNT,
        "versionsAnswered": COUNT, "versionsUnlisted": COUNT,
        "mostlyUnlisted": {"type": "boolean"},
        "note": {"type": "string", "minLength": 1},
    },
    "allOf": [{"if": {"properties": {"mostlyUnlisted": {"const": True}}},
               "then": {"required": ["note"]}, "else": {"not": {"required": ["note"]}}}],
}

package = defs["package"]
package["properties"]["unlistedFeeds"] = {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/unlistedFeed"}}
package["properties"]["listingNote"] = {"type": "string", "minLength": 1}
package["allOf"] += [
    # Unlisted feeds go with only_unlisted, and only_unlisted names them; a listing note never goes with an unknown.
    {"if": {"required": ["unlistedFeeds"]},
     "then": {"required": ["unknownCause"], "properties": {"unknownCause": {"const": "only_unlisted"}}}},
    {"if": {"required": ["unknownCause"], "properties": {"unknownCause": {"const": "only_unlisted"}}},
     "then": {"required": ["unlistedFeeds"]}},
    {"if": {"properties": {"outcome": {"const": "unknown"}}},
     "then": {"not": {"required": ["listingNote"]}}},
]

summary = schema["properties"]["summary"]
summary["properties"]["feedListing"] = {"type": "array", "items": {"$ref": "#/$defs/feedListing"}}

out = HERE / "dependency-assessment-1.9.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
