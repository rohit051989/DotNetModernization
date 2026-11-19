"""Writes dependency-assessment-1.7.0.schema.json from 1.6.0.

1.7.0 (additive, 38-PACKAGE-ACCESS.md Part B): an unknown package says why, as a code. Three optional properties on a
package, written only when its outcome is `unknown`:
  unknownCause    feed_auth | feed_unreachable | not_on_feed | version_unresolved
  failedFeeds     for feed_auth and feed_unreachable: each feed that failed (name, normalised url, failure, httpStatus)
  consultedFeeds  for not_on_feed: each feed that was asked (name, normalised url)
A package unknown for another reason (a lookup answered offline from a frozen snapshot) carries none of them.
No credential, userinfo, token or query string is ever in these fields (Part B4): urls are normalised.
dependency-assessment-1.6.0.schema.json is kept as written.
Run from this folder:  python make_dependency_schema_1_7_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
schema = json.loads((HERE / "dependency-assessment-1.6.0.schema.json").read_text(encoding="utf-8-sig"))

schema["$id"] = schema["$id"].replace("1.6.0", "1.7.0")
schema["title"] = schema["title"].replace("1.6.0", "1.7.0")
schema["properties"]["artifactVersion"] = {"const": "1.7.0"}

NAME = {"type": "string", "minLength": 1}
URL = {"type": "string", "minLength": 1,
       "description": "Normalised: scheme, host, port, path; never userinfo, query or fragment (Part B4)."}
defs = schema["$defs"]
defs["unknownCause"] = {"enum": ["feed_auth", "feed_unreachable", "not_on_feed", "version_unresolved"]}
defs["failedFeed"] = {
    "type": "object", "additionalProperties": False,
    "required": ["name", "url", "failure", "httpStatus"],
    "properties": {
        "name": NAME, "url": URL,
        "failure": {"enum": ["auth", "unreachable"]},
        "httpStatus": {"type": ["integer", "null"], "minimum": 100, "maximum": 599},
    },
}
defs["consultedFeed"] = {
    "type": "object", "additionalProperties": False,
    "required": ["name", "url"],
    "properties": {"name": NAME, "url": URL},
}

package = defs["package"]
package["properties"]["unknownCause"] = {"$ref": "#/$defs/unknownCause"}
package["properties"]["failedFeeds"] = {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/failedFeed"}}
package["properties"]["consultedFeeds"] = {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/consultedFeed"}}

package["allOf"] += [
    # The cause fields belong to an unknown outcome only.
    {"if": {"properties": {"outcome": {"const": "unknown"}}},
     "else": {"not": {"anyOf": [{"required": ["unknownCause"]}, {"required": ["failedFeeds"]}, {"required": ["consultedFeeds"]}]}}},
    # Failed feeds go with an access cause; consulted feeds with not_on_feed.
    {"if": {"required": ["failedFeeds"]},
     "then": {"required": ["unknownCause"], "properties": {"unknownCause": {"enum": ["feed_auth", "feed_unreachable"]}}}},
    {"if": {"required": ["consultedFeeds"]},
     "then": {"required": ["unknownCause"], "properties": {"unknownCause": {"const": "not_on_feed"}}}},
]

out = HERE / "dependency-assessment-1.7.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
