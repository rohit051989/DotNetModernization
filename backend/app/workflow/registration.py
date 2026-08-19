"""Step registration service — see 11-STEP-CONTRACT.md's 'Step declaration' and
10-ENGINE-CONCEPTS.md's 'Contract change detection'.

Registration is an upsert keyed on step_name. Callers (routers, seed scripts)
own the transaction: this module flushes but never commits.
"""

import datetime

from sqlalchemy.orm import Session

from app import models
from app.workflow import semver
from app.workflow.definition.model import JobDefinitionFile
from app.workflow.definition.validator import ValidationErrorItem, _flatten_flow, validate_job_definition
from app.workflow.schemas import AffectedConsumer, ContractChangeWarning, StepDeclaration


def _max_produced_major(db: Session, artifact_type: str, exclude_step_name: str) -> int | None:
    """The highest major version of `artifact_type` already produced by any
    OTHER registered step, or None if nobody produces it yet."""
    majors: list[int] = []
    for reg in db.query(models.WfStepRegistration).filter(
        models.WfStepRegistration.step_name != exclude_step_name
    ):
        for produced in reg.produces:
            if produced["artifact_type"] == artifact_type:
                majors.append(semver.major_version(produced["artifact_version"]))
    return max(majors) if majors else None


def _affected_consumers(
    db: Session, artifact_type: str, new_version: str, exclude_step_name: str
) -> list[AffectedConsumer]:
    """Every OTHER registered step whose consumes range for `artifact_type`
    cannot accept `new_version`."""
    affected: list[AffectedConsumer] = []
    for reg in db.query(models.WfStepRegistration).filter(
        models.WfStepRegistration.step_name != exclude_step_name
    ):
        for consumed in reg.consumes:
            if consumed["artifact_type"] != artifact_type:
                continue
            if not semver.satisfies(new_version, consumed["version_range"]):
                affected.append(
                    AffectedConsumer(
                        step_name=reg.step_name,
                        owner_team=reg.owner_team,
                        consumed_version_range=consumed["version_range"],
                    )
                )
    return affected


def detect_contract_changes(
    db: Session, declaration: StepDeclaration
) -> list[ContractChangeWarning]:
    """Runs before the write. For each artifact type this declaration produces
    at a NEW major version (higher than any other step currently produces),
    reports every other registered step whose consumes range can no longer
    accept it."""
    warnings: list[ContractChangeWarning] = []
    for produced in declaration.produces:
        existing_max = _max_produced_major(db, produced.artifact_type, declaration.step_name)
        new_major = semver.major_version(produced.artifact_version)
        if existing_max is None or new_major <= existing_max:
            continue

        affected = _affected_consumers(
            db, produced.artifact_type, produced.artifact_version, declaration.step_name
        )
        if affected:
            warnings.append(
                ContractChangeWarning(
                    artifact_type=produced.artifact_type,
                    new_version=produced.artifact_version,
                    affected_steps=affected,
                )
            )
    return warnings


def revalidate_active_definitions_for_step(
    db: Session, step_name: str
) -> list[tuple[models.WfJobDefinition, list[ValidationErrorItem]]]:
    """Re-runs full validation against every ACTIVE job definition whose flow
    references `step_name` — called after that step's registration changes,
    per 22-STEP-SEQUENCING-AND-POLICY.md Part A: a step registering a new
    non-optional `consumes` can silently invalidate an already-active
    definition (rule 2 or the new rule 9), which would otherwise only
    surface at the next launch.

    A definition that becomes invalid this way is NOT deactivated — a
    currently-active definition isn't yanked out from under anything just
    because a later registration drifted; `validation_status` and
    `validation_errors` are updated so the drift is visible immediately, and
    it is returned here so the caller can report it. Only re-validates and
    returns definitions that actually reference `step_name`; unrelated
    active definitions are left untouched."""
    changed: list[tuple[models.WfJobDefinition, list[ValidationErrorItem]]] = []

    for row in db.query(models.WfJobDefinition).filter_by(is_active=True):
        definition = JobDefinitionFile.model_validate(row.definition)
        referenced_steps = {occ.step_name for occ in _flatten_flow(definition.flow)}
        if step_name not in referenced_steps:
            continue

        errors = validate_job_definition(db, definition, exclude_definition_id=row.id)
        row.validation_status = "invalid" if errors else "valid"
        row.validation_errors = [e.to_dict() for e in errors] or None
        if errors:
            changed.append((row, errors))

    if changed:
        db.flush()

    return changed


def register_step(
    db: Session, declaration: StepDeclaration
) -> tuple[models.WfStepRegistration, bool, list[ContractChangeWarning], list[tuple[models.WfJobDefinition, list[ValidationErrorItem]]]]:
    """Upserts a step registration by step_name. Returns (row, created,
    warnings, invalidated_definitions). Registration always succeeds —
    warnings and invalidated definitions are informational, not a
    rejection."""
    warnings = detect_contract_changes(db, declaration)

    row = db.get(models.WfStepRegistration, declaration.step_name)
    created = row is None
    if row is None:
        row = models.WfStepRegistration(step_name=declaration.step_name)
        db.add(row)

    row.lifecycle_step_no = declaration.lifecycle_step_no
    row.display_name = declaration.display_name
    row.owner_code = declaration.owner_code
    row.version = declaration.version
    row.owner_team = declaration.owner_team
    row.adapter_type = declaration.adapter_type
    row.adapter_config = declaration.adapter_config
    row.consumes = [c.model_dump() for c in declaration.consumes]
    row.produces = [p.model_dump() for p in declaration.produces]
    row.implementation_status = declaration.implementation_status
    row.updated_at = datetime.datetime.now(datetime.timezone.utc)

    db.flush()

    invalidated = revalidate_active_definitions_for_step(db, declaration.step_name)

    return row, created, warnings, invalidated


def list_steps(db: Session) -> list[models.WfStepRegistration]:
    return (
        db.query(models.WfStepRegistration)
        .order_by(models.WfStepRegistration.lifecycle_step_no)
        .all()
    )


def get_step(db: Session, step_name: str) -> models.WfStepRegistration | None:
    return db.get(models.WfStepRegistration, step_name)


def delete_step(db: Session, step_name: str) -> bool:
    """Hard delete — used only for throwaway/test registrations. Real steps
    are never removed this way; see implementation_status: deprecated."""
    row = db.get(models.WfStepRegistration, step_name)
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True
