"""YAML parsing for job definitions. See 12-JOB-DEFINITION-FORMAT.md.

Parsing (is this even a well-formed JobDefinitionFile?) is a distinct failure
mode from the semantic rules in validator.py, which run against an already
-parsed definition and assume its shape is sound.
"""

import hashlib

import yaml
from pydantic import ValidationError

from app.workflow.definition.model import JobDefinitionFile


class JobDefinitionParseError(Exception):
    pass


def parse_job_definition(yaml_text: str) -> JobDefinitionFile:
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise JobDefinitionParseError(f"invalid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise JobDefinitionParseError("job definition YAML must be a mapping at the top level")

    try:
        return JobDefinitionFile.model_validate(raw)
    except ValidationError as exc:
        raise JobDefinitionParseError(f"job definition does not match the expected shape: {exc}") from exc


def compute_checksum(yaml_text: str) -> str:
    return hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()
