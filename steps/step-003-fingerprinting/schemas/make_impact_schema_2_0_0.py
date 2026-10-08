"""Writes impact-analysis-2.0.0.schema.json — impact-analysis
(33-IMPACT-ANALYSIS.md Part I).

2.0.0, breaking: a resolution's `files` is replaced by three figures never
added together — `changed` (update, rewrite, delete), `created` and
`toReview`; the summary's `filesImpacted` by `changes`, `filesChanged`,
`newFiles` and `filesToReview`, which reconcile with `byAction`; entries
gain `details`. 1.0.0 stays for artifacts already written.

Run from this folder:  python make_impact_schema_2_0_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent

ACTIONS = ["update", "rewrite", "delete", "create", "review"]
NULLABLE_STRING = {"type": ["string", "null"]}
STRINGS = {"type": "array", "items": {"type": "string"}}
COUNT = {"type": "integer", "minimum": 0}


def obj(properties: dict, required: list | None = None) -> dict:
    return {"type": "object", "additionalProperties": False, "required": required or list(properties), "properties": properties}


action_counts = obj({a: COUNT for a in ACTIONS})

entry = obj({
    "filePath": NULLABLE_STRING,
    "proposedPath": NULLABLE_STRING,
    "description": NULLABLE_STRING,
    "action": {"enum": ACTIONS},
    "certainty": {"enum": ["confirmed", "possible"]},
    "reasons": {"type": "array", "minItems": 1, "items": obj({
        "ruleId": {"type": "string"}, "action": {"enum": ACTIONS}, "reason": {"type": "string"},
    })},
    "traversalPaths": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    "details": STRINGS,
})
# Part F: a create names a proposed path and no existing file; anything else names a file.
entry["allOf"] = [{
    "if": {"properties": {"action": {"const": "create"}}},
    "then": {"properties": {"filePath": {"type": "null"}, "proposedPath": {"type": "string"}, "description": {"type": "string"}}},
    "else": {"properties": {"filePath": {"type": "string"}}},
}]

resolution = obj({
    "resolutionId": {"type": "string"},
    "name": {"type": "string"},
    "roles": {"type": "array", "minItems": 1, "items": {"enum": ["default", "presumptive", "chosen"]}},
    "effective": {"type": "boolean"},
    "rulesSource": {"enum": ["explicit", "default"]},
    "decisionResolutionId": NULLABLE_STRING,
    "counts": action_counts,
    "changed": COUNT,
    "created": COUNT,
    "toReview": COUNT,
    "confirmed": COUNT,
    "possible": COUNT,
    "entries": {"type": "array", "items": entry},
    "knownLimits": STRINGS,
    "deferredRules": STRINGS,
})

rollup_item = obj({
    "itemId": {"type": "string"}, "projectPath": {"type": "string"}, "resolutionId": {"type": "string"},
    "action": {"enum": ACTIONS}, "source": {"enum": ["structural", "client"]},
})

schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://modernization-platform.local/schemas/impact-analysis-2.0.0.schema.json",
    "title": "impact-analysis 2.0.0",
    "description": "impact-analysis (33-IMPACT-ANALYSIS.md): per work item, the files its conversion touches under "
                   "the default resolution and, where decided, the chosen one — each with an action, a certainty and a "
                   "traversal path, counted as files changed, new files and files to review, never added together; per file, the work items touching it under their effective resolutions, with hotspots "
                   "and conflicts. Structural only: client impact is added by dependency-and-context-map. Deterministic, no LLM.",
    **obj({
        "artifactVersion": {"const": "2.0.0"},
        "repositoryId": {"type": "string", "format": "uuid"},
        "repositorySlug": {"type": "string"},
        "engagementId": {"type": "string"},
        "summary": obj({
            "workItems": COUNT, "changes": COUNT, "filesChanged": COUNT, "byAction": action_counts,
            "newFiles": COUNT, "filesToReview": COUNT, "hotspots": COUNT, "conflicts": COUNT,
        }),
        "workItems": {"type": "array", "items": obj({
            "itemId": {"type": "string"},
            "itemName": {"type": "string"},
            "projectPath": {"type": "string"},
            "projectId": {"type": ["string", "null"]},
            "effectiveResolutionId": {"type": "string"},
            "resolutions": {"type": "array", "minItems": 1, "items": resolution},
            "pendingResolutions": {"type": "array", "items": obj({"resolutionId": {"type": "string"}, "name": {"type": "string"}})},
        })},
        "rollup": {"type": "array", "items": obj({
            "fileKey": {"type": "string"},
            "workItems": {"type": "array", "minItems": 1, "items": rollup_item},
            "hotspot": {"type": "boolean"},
            "conflicts": {"type": "array", "items": obj({
                "kind": {"enum": ["delete_with_change", "create_same_path"]}, "first": rollup_item, "second": rollup_item,
            })},
        })},
        "warnings": {"type": "array", "items": obj({
            "code": {"type": "string"}, "message": {"type": "string"}, "severity": {"enum": ["info", "warning", "error"]},
        })},
    }),
}

out = HERE / "impact-analysis-2.0.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
