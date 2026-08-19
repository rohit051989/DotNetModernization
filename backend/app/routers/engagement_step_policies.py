"""Engagement step policy — see 22-STEP-SEQUENCING-AND-POLICY.md Part C.

Configuration, not design: "does this client want this step at all?" Kept
separate from the job definition (which stays in git) precisely so an
operator can turn a step off for one engagement with no version bump — see
that doc's "two-layer principle".
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error, errors
from app.workflow import policy
from app.workflow.policy_schemas import (
    PolicyOrphansDependentsResponse,
    PolicyRevertOrphansResponse,
    StepPolicyOut,
    StepPolicyRequest,
    StepPolicySetResult,
    StepPolicyValidateRequest,
    StepPolicyValidateResponse,
)

router = APIRouter(prefix="/api/engagements/{engagement_id}/step-policies", tags=["Step Policies"])

_NO_ENGAGEMENT = {"model": ErrorResponse, "description": "No engagement exists with this id."}
_NO_STEP = {"model": ErrorResponse, "description": "No step is registered with this step_name."}


def _require_engagement(db: Session, engagement_id: str) -> models.Engagement:
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    return engagement


@router.get(
    "",
    response_model=list[StepPolicyOut],
    summary="List step policies for an engagement",
    response_description="Every explicit policy row for this engagement. A step with no row here is enabled.",
    operation_id="list_engagement_step_policies",
    responses={404: _NO_ENGAGEMENT},
)
def list_step_policies(engagement_id: str, db: Session = Depends(get_db)):
    _require_engagement(db, engagement_id)
    return policy.list_policies(db, engagement_id)


@router.post(
    "",
    response_model=StepPolicySetResult,
    summary="Enable or disable a lifecycle step for an engagement",
    response_description="The stored policy, plus any cascaded policy rows created.",
    operation_id="set_engagement_step_policy",
    responses={
        404: {"model": ErrorResponse, "description": "No engagement exists with this id, or step_name is not registered."},
        409: {
            "model": PolicyOrphansDependentsResponse,
            "description": "Disabling this step would leave a downstream step's required input unsatisfied. "
            "Retry with cascade: true to disable the named dependents in the same request.",
        },
    },
)
def set_step_policy(engagement_id: str, payload: StepPolicyRequest, db: Session = Depends(get_db)):
    """
    Upserts by `(engagement_id, step_name)`. Absence of a row means enabled —
    setting `enabled: true` is only needed to explicitly re-confirm a step or
    revert a policy without deleting it (see `DELETE` for the more common
    revert-to-default path).

    Disabling a step whose non-optional output some other step still relies
    on is refused (`POLICY_ORPHANS_DEPENDENTS`, 409) unless `cascade: true` is
    set, in which case every named dependent is disabled in the same request
    with reason `"cascaded from disabling <step_name>"`. A step whose only
    dependents consume it `optional: true` is unaffected and never blocks.
    """
    _require_engagement(db, engagement_id)
    if db.get(models.WfStepRegistration, payload.step_name) is None:
        raise error(404, f"Step '{payload.step_name}' is not registered", field="step_name", code="NOT_FOUND")

    if payload.enabled:
        row = policy.upsert_policy(
            db, engagement_id, payload.step_name, enabled=True, reason=payload.reason, set_by=payload.set_by
        )
        db.commit()
        db.refresh(row)
        return StepPolicySetResult(policy=StepPolicyOut.model_validate(row))

    # Structural — every step that would lose its required input, evaluated
    # against the job definition graph itself rather than the current policy
    # overlay. Not filtered by "is that dependent already disabled": nothing
    # cascades implicitly (Part C), so every disable of a step with
    # dependents must explicitly re-acknowledge all of them via cascade,
    # even if a dependent happens to already be off for its own reasons.
    outstanding = policy.find_dependents(db, payload.step_name)

    if outstanding and not payload.cascade:
        raise errors(
            409,
            [
                {
                    "code": "POLICY_ORPHANS_DEPENDENTS",
                    "message": (
                        f"Disabling {payload.step_name} would leave "
                        f"{', '.join(outstanding)} without its required input."
                    ),
                    "dependent_steps": outstanding,
                    "resolution": "Disable the dependent steps in the same request, or leave this step enabled.",
                }
            ],
        )

    row = policy.upsert_policy(
        db, engagement_id, payload.step_name, enabled=False, reason=payload.reason, set_by=payload.set_by
    )

    cascaded_rows = [
        policy.upsert_policy(
            db,
            engagement_id,
            dependent,
            enabled=False,
            reason=f"{policy.CASCADE_REASON_PREFIX}{payload.step_name}",
            set_by=payload.set_by,
        )
        for dependent in outstanding
    ]

    db.commit()
    db.refresh(row)
    for cascaded_row in cascaded_rows:
        db.refresh(cascaded_row)

    return StepPolicySetResult(
        policy=StepPolicyOut.model_validate(row),
        cascaded=[StepPolicyOut.model_validate(r) for r in cascaded_rows],
    )


@router.post(
    "/validate",
    response_model=StepPolicyValidateResponse,
    summary="Dry-run a step policy change",
    response_description="What would happen — no row is created or changed either way.",
    operation_id="validate_engagement_step_policy",
    responses={404: {"model": ErrorResponse, "description": "No engagement exists with this id, or step_name is not registered."}},
)
def validate_step_policy(engagement_id: str, payload: StepPolicyValidateRequest, db: Session = Depends(get_db)):
    """
    Lets the UI warn before the operator commits: same dependency check
    `POST` runs, without `cascade`, `reason`, or any write. `enabled: true`
    always reports `would_orphan: false` — enabling a step never orphans
    anything.
    """
    _require_engagement(db, engagement_id)
    if db.get(models.WfStepRegistration, payload.step_name) is None:
        raise error(404, f"Step '{payload.step_name}' is not registered", field="step_name", code="NOT_FOUND")

    if payload.enabled:
        return StepPolicyValidateResponse(would_orphan=False, dependent_steps=[], message=None)

    dependents = policy.find_dependents(db, payload.step_name)
    if not dependents:
        return StepPolicyValidateResponse(would_orphan=False, dependent_steps=[], message=None)

    return StepPolicyValidateResponse(
        would_orphan=True,
        dependent_steps=dependents,
        message=f"Disabling {payload.step_name} would leave {', '.join(dependents)} without its required input.",
    )


@router.delete(
    "/{step_name}",
    status_code=204,
    summary="Revert a step policy to the default (enabled)",
    response_description="Deleted. The step is enabled again — absence of a row means enabled.",
    operation_id="delete_engagement_step_policy",
    responses={
        404: {"model": ErrorResponse, "description": "No engagement exists with this id, or no policy row exists for this step_name."},
        409: {
            "model": PolicyRevertOrphansResponse,
            "description": "This step was disabled; reverting would re-enable it while a step it depends on for a "
            "required input is still disabled. Retry with ?force=true to accept the orphaned state.",
        },
    },
)
def delete_step_policy(
    engagement_id: str,
    step_name: str,
    force: bool = Query(
        default=False,
        description="Revert even if this step's required input's producer is still disabled by policy.",
    ),
    db: Session = Depends(get_db),
):
    """
    Deletes the policy row outright — the step reverts to enabled (absence
    means enabled). Deleting a policy that was itself created by a cascade
    does not **silently** re-enable an orphaned dependent: if this step is
    currently disabled and re-enabling it would leave it without a required
    input from another step still disabled by policy, this is refused
    (`POLICY_REVERT_ORPHANS_STEP`, 409) unless `force=true` — see
    22-STEP-SEQUENCING-AND-POLICY.md's acceptance criteria.
    """
    _require_engagement(db, engagement_id)
    row = policy.get_policy(db, engagement_id, step_name)
    if row is None:
        raise error(404, f"No step policy for '{step_name}' on engagement '{engagement_id}'", code="NOT_FOUND")

    if not row.enabled and not force:
        blocking = policy.find_blocking_producers(db, engagement_id, step_name)
        if blocking:
            raise errors(
                409,
                [
                    {
                        "code": "POLICY_REVERT_ORPHANS_STEP",
                        "message": (
                            f"Re-enabling {step_name} would leave it without its required input from "
                            f"{', '.join(blocking)}, still disabled by policy."
                        ),
                        "blocking_steps": blocking,
                        "resolution": "Re-enable the blocking step(s) first, or retry with ?force=true to accept the orphaned state.",
                    }
                ],
            )

    policy.delete_policy(db, engagement_id, step_name)
    db.commit()
