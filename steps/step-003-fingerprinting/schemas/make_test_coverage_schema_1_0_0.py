"""Writes test-coverage-1.0.0.schema.json — lifecycle step 8, phase 1
(32-TEST-COVERAGE-ASSESSMENT.md Part J).

Run from this folder:  python make_test_coverage_schema_1_0_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent

TEST_TYPES = ["unit", "integration", "functional", "smoke", "unclassified"]
BUCKETS = ["has_tests", "missing_tests", "no_testable_logic"]
NULLABLE_STRING = {"type": ["string", "null"]}
NULLABLE_PCT = {"type": ["number", "null"], "minimum": 0, "maximum": 100}
STRINGS = {"type": "array", "items": {"type": "string"}}


def obj(properties: dict, required: list | None = None) -> dict:
    return {"type": "object", "additionalProperties": False, "required": required or list(properties), "properties": properties}


def counts(keys: list) -> dict:
    return obj({k: {"type": "integer", "minimum": 0} for k in keys})


def not_measured_rule(pct: str, reason: str) -> dict:
    """Part E1: a figure is either a percentage, or no percentage and a reason. Never 0% for unknown."""
    return {
        "if": {"properties": {pct: {"type": "null"}}},
        "then": {"properties": {reason: {"type": "string", "minLength": 1}}},
        "else": {"properties": {reason: {"type": "null"}}},
    }


evidence = obj({
    "kind": {"enum": ["project_name", "category", "infrastructure", "connection_string", "service_url", "mocking"]},
    "value": {"type": "string"},
    "indicates": {"enum": TEST_TYPES[:-1]},
    "strength": {"enum": ["strong", "indicative", "supporting"]},
})

source_file = obj({
    "projectPath": {"type": "string"},
    "filePath": {"type": "string"},
    "bucket": {"enum": BUCKETS},
    "testableMembers": {"type": "integer", "minimum": 0},
    "testFiles": STRINGS,
    "testTypes": {"type": "array", "items": {"enum": TEST_TYPES}},
    "coverageSource": {"enum": ["existing_report", "not_measured"]},
    "linePct": NULLABLE_PCT,
    "branchPct": NULLABLE_PCT,
    "notMeasuredReason": NULLABLE_STRING,
    "unitLinePct": NULLABLE_PCT,
    "unitNotMeasuredReason": NULLABLE_STRING,
    "integrationLinePct": NULLABLE_PCT,
    "integrationNotMeasuredReason": NULLABLE_STRING,
})
source_file["allOf"] = [
    {
        "if": {"properties": {"coverageSource": {"const": "not_measured"}}},
        "then": {"properties": {"linePct": {"type": "null"}, "branchPct": {"type": "null"}, "notMeasuredReason": {"type": "string", "minLength": 1}}},
        "else": {"properties": {"linePct": {"type": "number"}, "notMeasuredReason": {"type": "null"}}},
    },
    not_measured_rule("unitLinePct", "unitNotMeasuredReason"),
    not_measured_rule("integrationLinePct", "integrationNotMeasuredReason"),
]

project = obj({
    "projectPath": {"type": "string"},
    "files": {"type": "integer", "minimum": 0},
    "hasTests": {"type": "integer", "minimum": 0},
    "missingTests": {"type": "integer", "minimum": 0},
    "noTestableLogic": {"type": "integer", "minimum": 0},
    "unitLinePct": NULLABLE_PCT,
    "unitNotMeasuredReason": NULLABLE_STRING,
    "integrationLinePct": NULLABLE_PCT,
    "integrationNotMeasuredReason": NULLABLE_STRING,
})
project["allOf"] = [not_measured_rule("unitLinePct", "unitNotMeasuredReason"),
                    not_measured_rule("integrationLinePct", "integrationNotMeasuredReason")]

schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://modernization-platform.local/schemas/test-coverage-1.0.0.schema.json",
    "title": "test-coverage 1.0.0",
    "description": "Lifecycle step 8, phase 1 (32-TEST-COVERAGE-ASSESSMENT.md): test classes and their type, source-to-test "
                   "mappings with confidence, every non-generated source file in exactly one bucket, coverage from existing "
                   "Cobertura / OpenCover / lcov reports, and CI maturity. No LLM, no test execution. A figure that is not "
                   "measured carries a reason and no percentage — never 0%. Deterministic for a given commit.",
    **obj({
        "artifactVersion": {"const": "1.0.0"},
        "repositoryId": {"type": "string", "format": "uuid"},
        "repositorySlug": {"type": "string"},
        "commitSha": NULLABLE_STRING,
        "summary": obj({
            "testProjects": {"type": "integer", "minimum": 0},
            "testClasses": {"type": "integer", "minimum": 0},
            "testMethods": {"type": "integer", "minimum": 0},
            "testClassesByType": counts(TEST_TYPES),
            "sourceFiles": {"type": "integer", "minimum": 0},
            "sourceFilesByBucket": counts(BUCKETS),
            "mappings": {"type": "integer", "minimum": 0},
            "coverageReports": {"type": "integer", "minimum": 0},
            "sourceFilesMeasured": {"type": "integer", "minimum": 0},
        }),
        "testProjects": {"type": "array", "items": obj({
            "projectPath": {"type": "string"},
            "reason": {"type": "string"},
            "testClasses": {"type": "integer", "minimum": 0},
            "testClassesByType": counts(TEST_TYPES),
        })},
        "testClasses": {"type": "array", "items": obj({
            "projectPath": {"type": "string"},
            "filePath": {"type": "string"},
            "className": {"type": "string"},
            "namespace": NULLABLE_STRING,
            "lineStart": {"type": "integer", "minimum": 1},
            "testType": {"enum": TEST_TYPES},
            "classificationReason": {"type": "string", "minLength": 1},
            "evidence": {"type": "array", "items": evidence},
            "testCount": {"type": "integer", "minimum": 1},
        })},
        "mappings": {"type": "array", "items": obj({
            "sourceFile": {"type": "string"},
            "productionType": {"type": "string"},
            "testFile": {"type": "string"},
            "testClass": {"type": "string"},
            "testType": {"enum": TEST_TYPES},
            "testMethods": STRINGS,
            "method": {"enum": ["type_reference", "type_reference+naming", "naming_only"]},
            "confidence": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
            "evidence": STRINGS,
        })},
        "projects": {"type": "array", "items": project},
        "sourceFiles": {"type": "array", "items": source_file},
        "coverageReports": {"type": "array", "items": obj({
            "path": {"type": "string"},
            "format": {"enum": ["cobertura", "opencover", "lcov"]},
            "attribution": {"enum": ["unit", "integration", "unattributed"]},
            "attributionReason": {"type": "string"},
            "filesInReport": {"type": "integer", "minimum": 0},
            "filesMatched": {"type": "integer", "minimum": 0},
            "unmatchedPaths": STRINGS,
        })},
        "ciMaturity": obj({
            "hasPipeline": {"type": "boolean"},
            "runsTests": {"type": "boolean"},
            "collectsCoverage": {"type": "boolean"},
            "publishesCoverage": {"type": "boolean"},
            "enforcesCoverageGate": {"type": "boolean"},
            "pipelines": {"type": "array", "items": obj({
                "path": {"type": "string"},
                "system": {"enum": ["azure_pipelines", "github_actions", "jenkins", "teamcity"]},
            })},
            "evidence": {"type": "array", "items": obj({
                "fact": {"enum": ["runs_tests", "collects_coverage", "publishes_coverage", "enforces_coverage_gate"]},
                "path": {"type": "string"},
                "line": {"type": "integer", "minimum": 1},
                "text": {"type": "string"},
            })},
        }),
        "warnings": {"type": "array", "items": obj({
            "code": {"type": "string"}, "message": {"type": "string"}, "severity": {"enum": ["info", "warning", "error"]},
        })},
    }),
}

out = HERE / "test-coverage-1.0.0.schema.json"
out.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}")
