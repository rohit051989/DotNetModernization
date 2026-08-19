"""Job definition storage — see 12-JOB-DEFINITION-FORMAT.md's 'Registration
and activation' section. Callers (routers) own the transaction: this module
flushes but never commits.
"""

from sqlalchemy.orm import Session

from app import models
from app.workflow import policy
from app.workflow.definition.loader import compute_checksum, parse_job_definition
from app.workflow.definition.model import JobDefinitionFile
from app.workflow.definition.schemas import (
    ArtifactRefOut,
    FlowStepOut,
    FlowStepPolicyOut,
    JobDefinitionViewOut,
    JobParameterOut,
)
from app.workflow.definition.validator import ValidationErrorItem, validate_job_definition
from app.workflow.runtime.when_eval import render_when_prose


class DuplicateJobVersionError(Exception):
    """Rule 7 failed: job_name+version already has a row. Unlike the other
    seven rules, there is no row to store this against — wf_job_definitions
    has its own DB-level unique constraint on (job_name, version) — so this
    must be caught BEFORE the insert is attempted, not left to surface as a
    generic IntegrityError."""

    def __init__(self, errors: list[ValidationErrorItem]):
        super().__init__(errors[0].detail if errors else "duplicate job version")
        self.errors = errors


def validate_yaml(
    db: Session, yaml_text: str
) -> tuple[JobDefinitionFile, list[ValidationErrorItem]]:
    """Parses and runs the 8 semantic rules. Raises JobDefinitionParseError
    if the YAML doesn't even match the expected shape — a distinct failure
    from the semantic errors this returns."""
    definition = parse_job_definition(yaml_text)
    errors = validate_job_definition(db, definition)
    return definition, errors


def store_definition(
    db: Session, yaml_text: str, activate: bool = False
) -> tuple[models.WfJobDefinition, list[ValidationErrorItem]]:
    """Always persists the row, valid or not — per 12-JOB-DEFINITION-FORMAT.md,
    an invalid definition is stored with validation_status: invalid, just
    refused activation. `activate` is honoured only when validation passes.

    The one exception is DUPLICATE_JOB_VERSION (rule 7): raises instead of
    storing, since there is nothing new to persist.
    """
    definition, errors = validate_yaml(db, yaml_text)
    if any(e.code == "DUPLICATE_JOB_VERSION" for e in errors):
        raise DuplicateJobVersionError(errors)

    validation_status = "invalid" if errors else "valid"

    row = models.WfJobDefinition(
        job_name=definition.job_name,
        version=definition.version,
        definition=definition.model_dump(mode="json"),
        source_yaml=yaml_text,
        checksum=compute_checksum(yaml_text),
        validation_status=validation_status,
        validation_errors=[e.to_dict() for e in errors] or None,
        is_active=False,
    )
    db.add(row)
    db.flush()

    if activate and validation_status == "valid":
        _activate(db, row)

    return row, errors


def _activate(db: Session, row: models.WfJobDefinition) -> None:
    # Partial unique index (job_name WHERE is_active) means the old active
    # row must be cleared before this one is set, in the same flush.
    db.query(models.WfJobDefinition).filter(
        models.WfJobDefinition.job_name == row.job_name,
        models.WfJobDefinition.id != row.id,
    ).update({"is_active": False})
    row.is_active = True
    db.flush()


def activate_definition(db: Session, job_name: str, version: int) -> models.WfJobDefinition:
    row = db.query(models.WfJobDefinition).filter_by(job_name=job_name, version=version).first()
    if row is None:
        raise LookupError(f"'{job_name}' version {version} is not stored")
    if row.validation_status != "valid":
        raise ValueError(f"'{job_name}' version {version} is not valid and cannot be activated")
    _activate(db, row)
    return row


def get_active_definition(db: Session, job_name: str) -> models.WfJobDefinition | None:
    return db.query(models.WfJobDefinition).filter_by(job_name=job_name, is_active=True).first()


def list_active_definitions(db: Session) -> list[models.WfJobDefinition]:
    """Every job with a currently-active definition — the Workflow tab's
    jobs list (20-WORKFLOW-OBSERVABILITY-UI.md Part B) iterates this rather
    than a hardcoded job name."""
    return (
        db.query(models.WfJobDefinition)
        .filter_by(is_active=True)
        .order_by(models.WfJobDefinition.job_name)
        .all()
    )


def build_job_definition_view(
    db: Session, job_name: str, engagement_id: str | None
) -> JobDefinitionViewOut | None:
    """Read-only, resolved-for-display view of the active definition —
    22-STEP-SEQUENCING-AND-POLICY.md Part E. Returns None if there is no
    active definition for `job_name`. Policy state is merged in per step only
    when `engagement_id` is supplied; otherwise every step shows as enabled
    by default (nothing to merge)."""
    row = get_active_definition(db, job_name)
    if row is None:
        return None

    definition = JobDefinitionFile.model_validate(row.definition)
    step_names = [node.step for node in definition.flow]
    registrations = {
        reg.step_name: reg
        for reg in db.query(models.WfStepRegistration).filter(
            models.WfStepRegistration.step_name.in_(step_names)
        )
    }
    policies = (
        {p.step_name: p for p in policy.list_policies(db, engagement_id)} if engagement_id else {}
    )

    flow_out: list[FlowStepOut] = []
    implemented_count = 0
    for sequence, node in enumerate(definition.flow, start=1):
        reg = registrations.get(node.step)
        if reg is not None and reg.implementation_status == "implemented":
            implemented_count += 1

        policy_row = policies.get(node.step)
        policy_out = (
            FlowStepPolicyOut(enabled=policy_row.enabled, source="engagement", reason=policy_row.reason)
            if policy_row is not None
            else FlowStepPolicyOut(enabled=True, source="default", reason=None)
        )

        flow_out.append(
            FlowStepOut(
                sequence=sequence,
                step_name=node.step,
                lifecycle_step_no=reg.lifecycle_step_no if reg else None,
                display_name=reg.display_name if reg else node.step,
                owner_code=reg.owner_code if reg else "",
                adapter_type=reg.adapter_type if reg else "",
                implementation_status=reg.implementation_status if reg else "",
                step_version=reg.version if reg else "",
                consumes=[ArtifactRefOut(**c) for c in (reg.consumes if reg else [])],
                produces=[ArtifactRefOut(**p) for p in (reg.produces if reg else [])],
                inputs=node.inputs,
                when=node.when.model_dump(by_alias=True) if node.when else None,
                when_description=render_when_prose(node.when) if node.when else None,
                gate=node.gate.model_dump() if node.gate else None,
                policy=policy_out,
            )
        )

    return JobDefinitionViewOut(
        job_name=row.job_name,
        version=row.version,
        is_active=row.is_active,
        validation_status=row.validation_status,
        description=definition.description,
        implemented_step_count=implemented_count,
        step_count=len(flow_out),
        parameters=[
            JobParameterOut(
                name=p.name, type=p.type, required=p.required, default=p.default, description=p.description
            )
            for p in definition.parameters
        ],
        flow=flow_out,
        raw_yaml=row.source_yaml,
    )
