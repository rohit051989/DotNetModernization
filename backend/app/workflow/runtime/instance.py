"""Job parameter resolution and instance identity — see
10-ENGINE-CONCEPTS.md's 'Job parameters' / 'Job instance' vocabulary.

Re-running a job with identical parameters must resume the same instance
(`job_key` — a SHA-256 of the canonicalised parameters — is the identity),
not create a new one. Different parameters mean a different instance.
"""

import hashlib
import json

from sqlalchemy.orm import Session

from app import models
from app.workflow.definition.model import JobDefinitionFile


_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


class ParameterValidationError(Exception):
    """Carries errors in this API's shared shape (`field`/`message`/`code`)
    — see app/errors.py. Each error names the offending parameter and says
    whether it was missing, unknown, or the wrong type."""

    def __init__(self, errors: list[dict]):
        super().__init__("; ".join(e["message"] for e in errors))
        self.errors = errors


def resolve_parameters(job_name: str, definition: JobDefinitionFile, provided: dict) -> dict:
    """Applies declared defaults, enforces `required`, checks basic types,
    and rejects parameters the job definition does not declare. Every error
    points at `GET /api/workflow/jobs/{job_name}/parameters` for the full
    contract — see 18-API-CONVENTIONS.md Part B."""
    resolved: dict = {}
    problems: list[dict] = []
    declared_names = {p.name for p in definition.parameters}
    pointer = f"See GET /api/workflow/jobs/{job_name}/parameters for the full parameter list."

    for param in definition.parameters:
        if param.name in provided:
            value = provided[param.name]
            type_check = _TYPE_CHECKS.get(param.type)
            if type_check is not None and not type_check(value):
                problems.append(
                    {
                        "field": param.name,
                        "message": (
                            f"'{param.name}' must be of type '{param.type}', got "
                            f"{type(value).__name__}. {pointer}"
                        ),
                        "code": "WRONG_TYPE",
                    }
                )
            else:
                resolved[param.name] = value
        elif param.default is not None:
            resolved[param.name] = param.default
        elif param.required:
            problems.append(
                {
                    "field": param.name,
                    "message": f"missing required parameter '{param.name}'. {pointer}",
                    "code": "MISSING_REQUIRED_PARAMETER",
                }
            )
        else:
            resolved[param.name] = None

    for name in sorted(set(provided) - declared_names):
        problems.append(
            {
                "field": name,
                "message": f"'{name}' is not a declared parameter for '{job_name}'. {pointer}",
                "code": "UNKNOWN_PARAMETER",
            }
        )

    if problems:
        raise ParameterValidationError(problems)
    return resolved


def compute_job_key(parameters: dict) -> str:
    canonical = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_or_create_instance(
    db: Session, job_name: str, parameters: dict
) -> tuple[models.WfJobInstance, bool]:
    """Returns (instance, created). Looked up by (job_name, job_key) — the
    unique constraint on wf_job_instances is what makes this safe under
    concurrent launches."""
    job_key = compute_job_key(parameters)
    instance = (
        db.query(models.WfJobInstance).filter_by(job_name=job_name, job_key=job_key).first()
    )
    if instance is not None:
        return instance, False

    instance = models.WfJobInstance(job_name=job_name, job_key=job_key, parameters=parameters)
    db.add(instance)
    db.flush()
    return instance, True
