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


class ParameterValidationError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def resolve_parameters(definition: JobDefinitionFile, provided: dict) -> dict:
    """Applies declared defaults, enforces `required`, and rejects parameters
    the job definition does not declare."""
    resolved: dict = {}
    errors: list[str] = []
    declared_names = {p.name for p in definition.parameters}

    for param in definition.parameters:
        if param.name in provided:
            resolved[param.name] = provided[param.name]
        elif param.default is not None:
            resolved[param.name] = param.default
        elif param.required:
            errors.append(f"missing required parameter '{param.name}'")
        else:
            resolved[param.name] = None

    unknown = sorted(set(provided) - declared_names)
    if unknown:
        errors.append(f"unknown parameters: {', '.join(unknown)}")

    if errors:
        raise ParameterValidationError(errors)
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
