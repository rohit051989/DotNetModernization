"""Engagement step policy — see 22-STEP-SEQUENCING-AND-POLICY.md Part C.

The dependency guard (`find_dependents`) reuses the same satisfiability
check the job-definition validator uses for rule 2 — "would this step still
be satisfiable if `step_name` were removed from its ancestors?" — rather than
a separate ad hoc graph walk, so the two never drift apart.
"""

import datetime

from sqlalchemy.orm import Session

from app import models
from app.workflow.definition.model import JobDefinitionFile
from app.workflow.definition.validator import _check_consumes_satisfied, _flatten_flow, _producers_of

# The literal reason prefix a cascade-created row always carries — see
# models.EngagementStepPolicy and app/workflow/runtime/executor.py.
CASCADE_REASON_PREFIX = "cascaded from disabling "


def find_dependents(db: Session, step_name: str) -> list[str]:
    """Every step, in any active job definition, whose non-optional
    `consumes` on an artifact type `step_name` produces would become
    unsatisfied if `step_name` stopped running. A downstream step whose
    consumes is `optional: true` is never a dependent — "optional consumes
    exempt" (Part C: "Downstream steps whose consumes is optional: true are
    unaffected — they run without that input")."""
    dependents: set[str] = set()

    for job_def_row in db.query(models.WfJobDefinition).filter_by(is_active=True):
        definition = JobDefinitionFile.model_validate(job_def_row.definition)
        occurrences = _flatten_flow(definition.flow)
        step_names = {occ.step_name for occ in occurrences}
        if step_name not in step_names:
            continue

        registrations = {
            row.step_name: row
            for row in db.query(models.WfStepRegistration).filter(
                models.WfStepRegistration.step_name.in_(step_names)
            )
        }

        for occ in occurrences:
            if step_name not in occ.ancestors:
                continue
            reg = registrations.get(occ.step_name)
            if reg is None:
                continue
            for consumed in reg.consumes:
                if consumed.get("optional", False):
                    continue
                artifact_type = consumed["artifact_type"]
                version_range = consumed["version_range"]
                satisfied_with, _ = _check_consumes_satisfied(
                    artifact_type, version_range, occ.ancestors, registrations, definition.external_inputs
                )
                satisfied_without, _ = _check_consumes_satisfied(
                    artifact_type,
                    version_range,
                    occ.ancestors - {step_name},
                    registrations,
                    definition.external_inputs,
                )
                if satisfied_with and not satisfied_without:
                    dependents.add(occ.step_name)

    return sorted(dependents)


def find_blocking_producers(db: Session, engagement_id: str, step_name: str) -> list[str]:
    """The inverse of `find_dependents`: every producer `step_name` relies on
    via a non-optional `consumes`, where *every* producer of that artifact
    type among its ancestors is currently disabled by policy for this
    engagement. Re-enabling `step_name` while that holds would leave it
    without a required input — used by DELETE to warn before silently
    re-enabling a step into an orphaned state (22-STEP-SEQUENCING-AND-POLICY.md's
    acceptance criteria: "Deleting a policy row for a step disabled by
    cascade does not silently re-enable an orphaned dependent")."""
    disabled_steps = {p.step_name for p in list_policies(db, engagement_id) if not p.enabled}
    blocking: set[str] = set()

    for job_def_row in db.query(models.WfJobDefinition).filter_by(is_active=True):
        definition = JobDefinitionFile.model_validate(job_def_row.definition)
        occurrences = _flatten_flow(definition.flow)
        step_names = {occ.step_name for occ in occurrences}
        if step_name not in step_names:
            continue

        registrations = {
            row.step_name: row
            for row in db.query(models.WfStepRegistration).filter(
                models.WfStepRegistration.step_name.in_(step_names)
            )
        }
        occ = next((o for o in occurrences if o.step_name == step_name), None)
        reg = registrations.get(step_name)
        if occ is None or reg is None:
            continue

        for consumed in reg.consumes:
            if consumed.get("optional", False):
                continue
            producers = _producers_of(consumed["artifact_type"], occ.ancestors, registrations)
            if producers and all(p in disabled_steps for p in producers):
                blocking.update(producers)

    return sorted(blocking)


def list_policies(db: Session, engagement_id: str) -> list[models.EngagementStepPolicy]:
    return (
        db.query(models.EngagementStepPolicy)
        .filter_by(engagement_id=engagement_id)
        .order_by(models.EngagementStepPolicy.step_name)
        .all()
    )


def get_policy(db: Session, engagement_id: str, step_name: str) -> models.EngagementStepPolicy | None:
    return (
        db.query(models.EngagementStepPolicy)
        .filter_by(engagement_id=engagement_id, step_name=step_name)
        .first()
    )


def upsert_policy(
    db: Session,
    engagement_id: str,
    step_name: str,
    enabled: bool,
    reason: str | None,
    set_by: str | None,
) -> models.EngagementStepPolicy:
    row = get_policy(db, engagement_id, step_name)
    now = datetime.datetime.now(datetime.timezone.utc)
    if row is None:
        row = models.EngagementStepPolicy(engagement_id=engagement_id, step_name=step_name)
        db.add(row)
    row.enabled = enabled
    row.reason = reason
    row.set_by = set_by
    row.set_at = now
    row.updated_at = now
    db.flush()
    return row


def delete_policy(db: Session, engagement_id: str, step_name: str) -> bool:
    row = get_policy(db, engagement_id, step_name)
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True
