"""Writes dependency-hierarchy-1.0.0.schema.json — the dependency-hierarchy step (37-DEPENDENCY-HIERARCHY.md Part C).

Run from this folder:  python make_dependency_hierarchy_schema_1_0_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent

NULLABLE_STRING = {"type": ["string", "null"]}
STRINGS = {"type": "array", "items": {"type": "string"}}
COUNT = {"type": "integer", "minimum": 0}
COUNTS = {"type": "object", "additionalProperties": COUNT}


def obj(properties: dict, required: list | None = None) -> dict:
    return {"type": "object", "additionalProperties": False, "required": required or list(properties), "properties": properties}


def nullable(schema: dict) -> dict:
    return {"anyOf": [{"type": "null"}, schema]}


warning = obj({"code": {"type": "string"}, "message": {"type": "string"}, "severity": {"enum": ["info", "warning", "error"]}})

project = obj({
    "projectId": {"type": ["string", "null"], "format": "uuid"},
    "path": {"type": "string", "minLength": 1},
    "kind": {"enum": ["application", "library", "test", "other"]},
    "kindBasis": {"type": "string", "minLength": 1},
    "targetFrameworks": STRINGS,
    "projectFormat": {"enum": ["sdk_style", "legacy_msbuild", "unknown"]},
    "packageManagement": {"enum": ["packagereference", "packages_config", "mixed", "none"]},
})

producer = obj({
    "repositoryId": {"type": "string", "format": "uuid"},
    "repositoryName": {"type": "string"},
    "projectPath": {"type": "string"},
})

findings = obj({
    "outcome": {"enum": ["current", "upgrade_safe", "upgrade_breaking", "no_compatible_version", "unknown", "framework_provided"]},
    "outcomeReason": NULLABLE_STRING,
    "recommendedVersion": NULLABLE_STRING,
    "outdated": {"type": "boolean"},
    "deprecated": {"type": "boolean"},
    "vulnerable": {"type": "boolean"},
    "vulnerabilityMaxSeverity": NULLABLE_STRING,
})

package = obj({
    "packageId": {"type": "string", "minLength": 1},
    "version": NULLABLE_STRING,
    "origin": {"enum": ["internal", "external", "unknown"]},
    "originBasis": {"type": "string", "minLength": 1},
    "feedName": NULLABLE_STRING,
    "feedUrl": NULLABLE_STRING,
    "transitive": {"type": "boolean"},
    "producer": nullable(producer),
    "findings": nullable(findings),
    "vulnerabilityMaxSeverity": {"enum": [None, "low", "moderate", "high", "critical"]},
    "dependenciesResolution": {"enum": [None, "assets_file", "feed_metadata"]},
    "dependenciesNotCheckedReason": NULLABLE_STRING,
})

assembly = obj({
    "assemblyName": {"type": "string", "minLength": 1},
    "version": NULLABLE_STRING,
    "location": {"enum": ["repository", "outside_repository", "gac", "framework"]},
    "path": NULLABLE_STRING,
    "exists": {"type": ["boolean", "null"]},
})

node = obj({
    "id": {"type": "string", "pattern": "^(project|package|assembly):.+"},
    "type": {"enum": ["project", "package", "assembly"]},
    "name": {"type": "string", "minLength": 1},
    "status": {"enum": ["checked", "not_checked"]},
    "notCheckedReason": NULLABLE_STRING,
    "project": nullable(project),
    "package": nullable(package),
    "assembly": nullable(assembly),
})
node["allOf"] = [
    # Not checked always says why; checked never carries a reason.
    {
        "if": {"properties": {"status": {"const": "not_checked"}}},
        "then": {"properties": {"notCheckedReason": {"type": "string", "minLength": 1}}},
        "else": {"properties": {"notCheckedReason": {"type": "null"}}},
    },
    # The detail matching the node's type, and only that one.
    {"if": {"properties": {"type": {"const": "project"}}},
     "then": {"properties": {"project": {"type": "object"}, "package": {"type": "null"}, "assembly": {"type": "null"}}}},
    {"if": {"properties": {"type": {"const": "package"}}},
     "then": {"properties": {"package": {"type": "object"}, "project": {"type": "null"}, "assembly": {"type": "null"}}}},
    {"if": {"properties": {"type": {"const": "assembly"}}},
     "then": {"properties": {"assembly": {"type": "object"}, "project": {"type": "null"}, "package": {"type": "null"}}}},
]

edge = obj({
    "from": {"type": "string"},
    "to": {"type": "string"},
    "kind": {"enum": ["project_reference", "package_reference", "central_package_version", "packages_config", "assembly_reference", "package_dependency"]},
    "resolution": {"enum": ["declared", "assets_file", "feed_metadata"]},
    "versionRequested": NULLABLE_STRING,
    "frameworks": STRINGS,
    "declaredAt": nullable(obj({"filePath": {"type": "string"}, "line": {"type": ["integer", "null"], "minimum": 1}})),
    "closesCycle": {"type": "boolean"},
})

schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://modernization-platform/schemas/dependency-hierarchy-1.0.0.schema.json",
    "title": "dependency-hierarchy 1.0.0",
    **obj({
        "artifactType": {"const": "dependency-hierarchy"},
        "artifactVersion": {"const": "1.0.0"},
        "scannerVersion": {"type": "string"},
        "repositoryId": {"type": "string", "format": "uuid"},
        "repositorySlug": {"type": "string"},
        "limits": obj({"maxPackageDepth": {"type": "integer", "minimum": 1}, "maxPackages": {"type": "integer", "minimum": 1}}),
        "summary": obj({
            "projectCount": COUNT,
            "countByProjectKind": COUNTS,
            "packageCount": COUNT,
            "internalPackageCount": COUNT,
            "externalPackageCount": COUNT,
            "transitivePackageCount": COUNT,
            "assemblyCount": COUNT,
            "edgeCount": COUNT,
            "countByEdgeKind": COUNTS,
            "rootCount": COUNT,
            "cycleCount": COUNT,
            "notCheckedCount": COUNT,
            "depth": COUNT,
        }),
        "roots": STRINGS,
        "nodes": {"type": "array", "items": node},
        "edges": {"type": "array", "items": edge},
        "cycles": {"type": "array", "items": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
        "warnings": {"type": "array", "items": warning},
    }),
}

(HERE / "dependency-hierarchy-1.0.0.schema.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8", newline="\n")
print("wrote dependency-hierarchy-1.0.0.schema.json")
