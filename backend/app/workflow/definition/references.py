"""${...} reference extraction for job definitions — see
12-JOB-DEFINITION-FORMAT.md's four reference forms:

    ${params.x}              a declared job parameter
    ${external.x}             a declared external_inputs entry (by logical_name)
    ${steps.x.outputs.y}      an upstream step's declared output, by step + type
    ${artifacts.x}            the first upstream producer of artifact type x

Extraction only — classification and resolution happen in validator.py, where
the surrounding flow/registration context is available.
"""

from dataclasses import dataclass
from typing import Any

import re

_REF_PATTERN = re.compile(r"\$\{([a-zA-Z_][\w.\-]*)\}")


@dataclass(frozen=True)
class Reference:
    raw: str  # e.g. "params.engagement_id" — the token with ${} stripped
    step_name: str  # the step occurrence this reference was found on
    field: str  # "inputs" or "config", for error messages

    @property
    def kind(self) -> str:
        return self.raw.split(".", 1)[0]

    @property
    def parts(self) -> list[str]:
        return self.raw.split(".")


def _strings_in(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings_in(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings_in(v)]
    return []


def extract_references(step_name: str, field: str, value: Any) -> list[Reference]:
    """Every `${...}` token found anywhere inside `value` (a step's `inputs`
    or `config`, which may nest dicts/lists)."""
    return [
        Reference(raw=match.group(1), step_name=step_name, field=field)
        for s in _strings_in(value)
        for match in _REF_PATTERN.finditer(s)
    ]
