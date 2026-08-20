"""Step policy — global and engagement layers. See
23-WORKFLOW-ADMINISTRATION.md Part A, which amends
22-STEP-SEQUENCING-AND-POLICY.md Part C with a third layer: default (no row),
global (`engagement_id IS NULL`, "nobody should run this yet"), and
engagement (`engagement_id` set, "this client does not want this").
Precedence is engagement beats global beats default.

The dependency guard (`find_dependents`) reuses the same satisfiability
check the job-definition validator uses for rule 2 — "would this step still
be satisfiable if `step_name` were removed from its ancestors?" — rather than
a separate ad hoc graph walk, so the two never drift apart. It is purely
structural and therefore scope-agnostic: the same check applies whether the
step being disabled is a global or an engagement-level change.
"""

import dataclasses
import datetime

from sqlalchemy.orm import Session

from app import models
from app.workflow.definition.model import JobDefinitionFile
from app.workflow.definition.validator import _check_consumes_satisfied, _flatten_flow, _producers_of

# The literal reason prefix a cascade-created row always carries — see
# models.StepPolicy and app/workflow/runtime/executor.py.
CASCADE_REASON_PREFIX = "cascaded from disabling "


@dataclasses.dataclass(frozen=True)
class EffectivePolicy:
    """One step's resolved state for a given scope — 23-WORKFLOW-ADMINISTRATION.md
    Part A's precedence rule, plus the raw rows so a caller (the definition
    viewer, `effective-policies`, `policy-matrix`) can show inheritance
    without recomputing it."""

    step_name: str
    enabled: bool
    source: str  # "engagement" | "global" | "default"
    reason: str | None
    global_policy: "models.StepPolicy | None"
    engagement_policy: "models.StepPolicy | None"


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


def _effectively_disabled_steps(db: Session, engagement_id: str | None) -> set[str]:
    """Every step whose effective state — resolved for `engagement_id` — is
    disabled. `engagement_id=None` resolves only global-vs-default, which is
    exactly the check a *global* re-enable needs; a non-null `engagement_id`
    resolves the full three-layer precedence, which is what an *engagement*
    re-enable needs (23-WORKFLOW-ADMINISTRATION.md Part A: "re-enabling a
    step whose upstream producer is globally disabled must be refused")."""
    global_rows = {r.step_name: r for r in list_policies(db, None)}
    engagement_rows = {r.step_name: r for r in list_policies(db, engagement_id)} if engagement_id else {}

    disabled: set[str] = set()
    for step_name in global_rows.keys() | engagement_rows.keys():
        engagement_row = engagement_rows.get(step_name)
        global_row = global_rows.get(step_name)
        effective_enabled = (
            engagement_row.enabled if engagement_row is not None
            else (global_row.enabled if global_row is not None else True)
        )
        if not effective_enabled:
            disabled.add(step_name)
    return disabled


def find_blocking_producers(db: Session, engagement_id: str | None, step_name: str) -> list[str]:
    """The inverse of `find_dependents`: every producer `step_name` relies on
    via a non-optional `consumes`, where *every* producer of that artifact
    type among its ancestors is currently effectively disabled for this
    scope. Re-enabling `step_name` while that holds would leave it without a
    required input — used by DELETE to warn before silently re-enabling a
    step into an orphaned state (22-STEP-SEQUENCING-AND-POLICY.md's
    acceptance criteria, extended across layers by
    23-WORKFLOW-ADMINISTRATION.md Part A). Pass `engagement_id=None` for the
    global scope's own re-enable guard."""
    disabled_steps = _effectively_disabled_steps(db, engagement_id)
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


def find_overriding_engagements(db: Session, step_name: str) -> list[str]:
    """Engagements with their own row explicitly re-enabling `step_name` —
    reported alongside a global disable so the admin knows the change is
    partial (23-WORKFLOW-ADMINISTRATION.md Part A)."""
    rows = (
        db.query(models.StepPolicy)
        .filter(
            models.StepPolicy.engagement_id.is_not(None),
            models.StepPolicy.step_name == step_name,
            models.StepPolicy.enabled.is_(True),
        )
        .order_by(models.StepPolicy.engagement_id)
        .all()
    )
    return [r.engagement_id for r in rows]


def list_policies(db: Session, engagement_id: str | None) -> list[models.StepPolicy]:
    """`engagement_id=None` lists global rows; otherwise, that engagement's
    rows."""
    query = db.query(models.StepPolicy)
    query = query.filter(models.StepPolicy.engagement_id.is_(None)) if engagement_id is None \
        else query.filter(models.StepPolicy.engagement_id == engagement_id)
    return query.order_by(models.StepPolicy.step_name).all()


def get_policy(db: Session, engagement_id: str | None, step_name: str) -> models.StepPolicy | None:
    query = db.query(models.StepPolicy).filter(models.StepPolicy.step_name == step_name)
    query = query.filter(models.StepPolicy.engagement_id.is_(None)) if engagement_id is None \
        else query.filter(models.StepPolicy.engagement_id == engagement_id)
    return query.first()


def upsert_policy(
    db: Session,
    engagement_id: str | None,
    step_name: str,
    enabled: bool,
    reason: str,
    set_by: str | None,
) -> models.StepPolicy:
    row = get_policy(db, engagement_id, step_name)
    now = datetime.datetime.now(datetime.timezone.utc)
    if row is None:
        row = models.StepPolicy(engagement_id=engagement_id, step_name=step_name)
        db.add(row)
    row.enabled = enabled
    row.reason = reason
    row.set_by = set_by
    row.set_at = now
    row.updated_at = now
    db.flush()
    return row


def delete_policy(db: Session, engagement_id: str | None, step_name: str) -> bool:
    row = get_policy(db, engagement_id, step_name)
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


def in_scope_step_names(db: Session) -> list[str]:
    """Every step name appearing in at least one active job definition — the
    set `effective-policies` and `policy-matrix` restrict themselves to
    (23-WORKFLOW-ADMINISTRATION.md Part B: "the other 44 have no policy
    meaning yet, and listing all 51 makes the matrix unreadable")."""
    names: set[str] = set()
    for job_def_row in db.query(models.WfJobDefinition).filter_by(is_active=True):
        definition = JobDefinitionFile.model_validate(job_def_row.definition)
        names.update(occ.step_name for occ in _flatten_flow(definition.flow))
    return sorted(names)


def resolve_effective_policies(
    db: Session, engagement_id: str | None, step_names: list[str]
) -> dict[str, EffectivePolicy]:
    """Resolve every name in `step_names` per the precedence rule. Pass
    `engagement_id=None` to resolve global-vs-default only (used for the
    master/global-only views)."""
    global_rows = {r.step_name: r for r in list_policies(db, None)}
    engagement_rows = {r.step_name: r for r in list_policies(db, engagement_id)} if engagement_id else {}

    resolved: dict[str, EffectivePolicy] = {}
    for name in step_names:
        engagement_row = engagement_rows.get(name)
        global_row = global_rows.get(name)
        if engagement_row is not None:
            resolved[name] = EffectivePolicy(
                name, engagement_row.enabled, "engagement", engagement_row.reason, global_row, engagement_row
            )
        elif global_row is not None:
            resolved[name] = EffectivePolicy(name, global_row.enabled, "global", global_row.reason, global_row, None)
        else:
            resolved[name] = EffectivePolicy(name, True, "default", None, None, None)
    return resolved
