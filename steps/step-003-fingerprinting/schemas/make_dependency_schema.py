"""Writes dependency-assessment-1.1.0.schema.json (30-STEP-006-DEPENDENCY-ASSESSMENT.md Part F).

1.1.0 (additive): packageKind, breakingEvidence, contentBreakingPossible,
versionDrift, callSites[].certainty, classificationMethod package_kind,
summary.versionDriftCount and contentBreakingPossibleCount.
dependency-assessment-1.0.0.schema.json is kept as written for 1.0.0 artifacts.

The signal, evidence and warning definitions are copied from
application-fingerprint-1.2.0 so the two artifacts cannot drift apart on
what a signal is. Run from this folder:  python make_dependency_schema.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
fingerprint = json.loads((HERE / "application-fingerprint-1.2.0.schema.json").read_text(encoding="utf-8"))
shared = {k: fingerprint["$defs"][k] for k in ("signalCategory", "signalType", "evidenceSourceType", "evidence", "signal", "signalEvidenceKind", "warning")}
# Step 6's evidence may say how certain a call site is (1.1.0); step 3's never does.
shared["evidence"] = {**shared["evidence"], "properties": {**shared["evidence"]["properties"],
                                                          "certainty": {"enum": ["confirmed", "ambiguous"]}}}

OUTCOMES = ["current", "upgrade_safe", "upgrade_breaking", "no_compatible_version", "unknown"]
FEED_SOURCES = ["client_feed", "nuget_org_fallback"]


def obj(required, properties, optional=()):
    """A closed object: every listed property is written (nulls included)
    except those named in optional."""
    return {"type": "object", "additionalProperties": False,
            "required": [k for k in required if k not in optional], "properties": properties}


def nullable(schema):
    if "$ref" in schema:
        return {"oneOf": [{"type": "null"}, schema]}
    return {**schema, "type": [schema["type"], "null"]}


S = {"type": "string", "minLength": 1}
COUNT = {"type": "integer", "minimum": 0}
counts = {"type": "object", "additionalProperties": COUNT}

defs = {
    **shared,
    "outcome": {"enum": OUTCOMES},
    "feedSource": {"enum": FEED_SOURCES},
    "sourceLine": obj(["filePath", "line"], {"filePath": S, "line": {"type": ["integer", "null"], "minimum": 1}}),
    "feed": obj(["name", "url", "role", "declaredIn"], {
        "name": S,
        "url": {**S, "description": "Normalised: never userinfo, query or fragment (Part B4)."},
        "role": {"enum": ["client_feed", "nuget_org", "ignored"]},
        "declaredIn": {"enum": ["repository", "user", "machine", "default"]},
    }),
    "deprecation": obj(["reasons", "message", "replacementId", "replacementRange"], {
        "reasons": {"type": "array", "items": S},
        "message": {"type": ["string", "null"]},
        "replacementId": {"type": ["string", "null"]},
        "replacementRange": {"type": ["string", "null"]},
    }),
    "advisory": obj(["severity", "url"], {"severity": {"enum": ["low", "moderate", "high", "critical"]}, "url": S}),
    "vulnerability": obj(["maxSeverity", "advisories", "resolvedByUpgrade"], {
        "maxSeverity": {"enum": ["low", "moderate", "high", "critical"]},
        "advisories": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/advisory"}},
        "resolvedByUpgrade": {"type": ["boolean", "null"]},
    }),
    "clientFeedGap": obj(["latestPublicVersion", "latestInClientFeed", "clientFeedName"], {
        "latestPublicVersion": S, "latestInClientFeed": {"type": ["string", "null"]}, "clientFeedName": S,
    }),
    "apiDiff": obj(["removedTypes", "removedMembers", "changedSignatures", "currentAssemblies", "recommendedAssemblies"], {
        "removedTypes": COUNT, "removedMembers": COUNT, "changedSignatures": COUNT, "currentAssemblies": S, "recommendedAssemblies": S,
    }),
    "breakingMember": obj(["change", "type", "member", "oldSignature", "newSignatures"], {
        "change": {"enum": ["type_removed", "member_removed", "signature_changed"]},
        "type": S, "member": {"type": ["string", "null"]}, "oldSignature": {"type": ["string", "null"]},
        "newSignatures": {"type": "array", "items": S},
    }),
    "callSite": obj(["filePath", "lineStart", "lineEnd", "member"], {
        "filePath": S, "lineStart": {"type": "integer", "minimum": 1}, "lineEnd": {"type": "integer", "minimum": 1}, "member": S,
        "certainty": {"enum": ["confirmed", "ambiguous"]},
    }),
    "package": {
        **obj(["assessmentId", "packageId", "currentVersion", "versionSource", "declaredAt", "recommendedVersion", "latestVersion",
               "outcome", "outcomeReason", "packageKind", "classificationMethod", "breakingEvidence", "contentBreakingPossible", "versionDrift",
               "semverChange", "deprecated", "vulnerable", "notInClientFeed",
               "feedSource", "feedName", "feedUrl", "apiDiff", "breakingMembers", "callSites", "confidence", "confidenceReasons"], {
            "assessmentId": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
            "packageId": S,
            "currentVersion": {"type": ["string", "null"]},
            "versionSource": {"enum": ["project", "central", "packages_config", "unresolved"]},
            "declaredAt": {"$ref": "#/$defs/sourceLine"},
            "recommendedVersion": {"type": ["string", "null"]},
            "latestVersion": {"type": ["string", "null"]},
            "outcome": {"$ref": "#/$defs/outcome"},
            "outcomeReason": {"type": ["string", "null"]},
            "packageKind": {"enum": ["runtime", "build", "tools", "analyzer", "content", None]},
            "classificationMethod": {"enum": ["api_diff", "semver_heuristic", "package_kind", None]},
            "breakingEvidence": {"enum": ["confirmed_call_sites", "ambiguous_call_sites_only", "semver_presumed", None]},
            "contentBreakingPossible": {"type": "boolean"},
            "versionDrift": {"type": "boolean"},
            "semverChange": {"enum": ["major", "minor", "patch", None]},
            "deprecated": nullable({"$ref": "#/$defs/deprecation"}),
            "vulnerable": nullable({"$ref": "#/$defs/vulnerability"}),
            "notInClientFeed": nullable({"$ref": "#/$defs/clientFeedGap"}),
            "feedSource": {"enum": FEED_SOURCES + [None]},
            "feedName": {"type": ["string", "null"]},
            "feedUrl": {"type": ["string", "null"]},
            "apiDiff": nullable({"$ref": "#/$defs/apiDiff"}),
            "breakingMembers": {"type": "array", "items": {"$ref": "#/$defs/breakingMember"}},
            "callSites": {"type": "array", "items": {"$ref": "#/$defs/callSite"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "confidenceReasons": {"type": "array", "items": S},
        }),
        "allOf": [
            # Only an upgrade is classified (Part C4).
            {"if": {"properties": {"outcome": {"enum": ["upgrade_safe", "upgrade_breaking"]}}},
             "then": {"required": ["recommendedVersion"], "properties": {"recommendedVersion": S, "classificationMethod": {"enum": ["api_diff", "semver_heuristic", "package_kind"]}}},
             "else": {"properties": {"classificationMethod": {"const": None}, "breakingMembers": {"maxItems": 0}, "callSites": {"maxItems": 0}}}},
            # unknown always says why (Part B7).
            {"if": {"properties": {"outcome": {"const": "unknown"}}}, "then": {"properties": {"outcomeReason": S}}},
            # Only a breaking outcome has breaking evidence, and it always has one.
            {"if": {"properties": {"outcome": {"const": "upgrade_breaking"}}},
             "then": {"properties": {"breakingEvidence": {"enum": ["confirmed_call_sites", "ambiguous_call_sites_only", "semver_presumed"]},
                                     "packageKind": {"enum": ["runtime", None]}}},
             "else": {"properties": {"breakingEvidence": {"const": None}}}},
            # The content flag is raised on a safe upgrade of a content package only.
            {"if": {"properties": {"contentBreakingPossible": {"const": True}}},
             "then": {"properties": {"outcome": {"const": "upgrade_safe"}, "packageKind": {"const": "content"}}}},
        ],
    },
    "transitivePackage": obj(["packageId", "version", "vulnerable"], {
        "packageId": S, "version": S, "vulnerable": nullable({"$ref": "#/$defs/vulnerability"}),
    }),
    "project": obj(["projectId", "projectPath", "status", "skipReason", "currentFramework", "feeds", "summary", "packages", "transitive", "signals", "warnings"], {
        "projectId": {"type": "string", "format": "uuid"},
        "projectPath": S,
        "status": {"enum": ["SCANNED", "SKIPPED", "FAILED"]},
        "skipReason": {"type": ["string", "null"]},
        "currentFramework": {"type": ["string", "null"]},
        "feeds": {"type": "array", "items": {"$ref": "#/$defs/feed"}},
        "summary": obj(["countByOutcome", "deprecatedCount", "vulnerableCount", "notInClientFeedCount"], {
            "countByOutcome": counts, "deprecatedCount": COUNT, "vulnerableCount": COUNT, "notInClientFeedCount": COUNT}),
        "packages": {"type": "array", "items": {"$ref": "#/$defs/package"}},
        "transitive": {"type": "array", "items": {"$ref": "#/$defs/transitivePackage"}},
        "signals": {"type": "array", "items": {"$ref": "#/$defs/signal"}},
        "warnings": {"type": "array", "items": {"$ref": "#/$defs/warning"}},
    }, optional=("transitive",)),
}

schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://modernization-platform.local/schemas/dependency-assessment-1.1.0.schema.json",
    "title": "dependency-assessment 1.1.0",
    "description": "Lifecycle step 6 (30-STEP-006-DEPENDENCY-ASSESSMENT.md). One assessment per project per direct package: the "
                   "recommended version for the engagement's target framework from the authoritative feed, the outcome, the "
                   "deprecated / vulnerable / not-in-client-feed flags, and for a breaking upgrade the changed members the code calls. "
                   "Deterministic against the lookup cache; no fetch time and nothing derived from a feed credential appears here.",
    **obj(["artifactType", "artifactVersion", "scannerVersion", "repositoryId", "repositorySlug", "targetFramework", "comparePublicFeed",
           "includeTransitive", "skipSource", "summary", "projects", "warnings"], {
        "artifactType": {"const": "dependency-assessment"},
        "artifactVersion": {"const": "1.1.0"},
        "scannerVersion": S,
        "repositoryId": {"type": "string", "format": "uuid"},
        "repositorySlug": S,
        "targetFramework": S,
        "comparePublicFeed": {"type": "boolean"},
        "includeTransitive": {"type": "boolean"},
        "skipSource": S,
        "summary": obj(["projectsScanned", "projectsSkipped", "projectsFailed", "packageCount", "countByOutcome", "countByFeedSource",
                        "deprecatedCount", "vulnerableCount", "notInClientFeedCount", "versionDriftCount", "contentBreakingPossibleCount"], {
            "projectsScanned": COUNT, "projectsSkipped": COUNT, "projectsFailed": COUNT, "packageCount": COUNT,
            "countByOutcome": {"type": "object", "additionalProperties": False, "properties": {o: COUNT for o in OUTCOMES}},
            "countByFeedSource": {"type": "object", "additionalProperties": False, "properties": {f: COUNT for f in FEED_SOURCES + ["none"]}},
            "deprecatedCount": COUNT, "vulnerableCount": COUNT, "notInClientFeedCount": COUNT,
            "versionDriftCount": COUNT, "contentBreakingPossibleCount": COUNT,
        }),
        "projects": {"type": "array", "items": {"$ref": "#/$defs/project"}},
        "warnings": {"type": "array", "items": {"$ref": "#/$defs/warning"}},
    }),
    "$defs": defs,
}

out = HERE / "dependency-assessment-1.1.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
