"""Global-layer step policy, and the resolved cross-layer views —
23-WORKFLOW-ADMINISTRATION.md Parts A and B. The engagement-layer endpoints
live in `app/routers/step_policies.py`; this file owns the layer
above it (`engagement_id IS NULL`, "nobody should run this yet") plus the
two read-only views that resolve both layers together.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error, errors
from app.workflow import policy
from app.workflow.policy_schemas import (
    EffectivePolicyOut,
    PolicyMatrixEngagementOut,
    PolicyMatrixOut,
    PolicyMatrixStepOut,
    PolicyOrphansDependentsResponse,
    PolicyRevertOrphansResponse,
    PolicyStateOut,
    StepPolicyOut,
    StepPolicyRequest,
    StepPolicySetResult,
    StepPolicyValidateRequest,
    StepPolicyValidateResponse,
)

router = APIRouter(prefix="/api/workflow", tags=["Step Policies"])

_NO_STEP = {"model": ErrorResponse, "description": "No step is registered with this step_name."}


@router.get(
    "/step-policies",
    response_model=list[StepPolicyOut],
    summary="List global step policies",
    response_description="Every explicit global-layer row. A step with no row here is enabled by default.",
    operation_id="list_global_step_policies",
)
def list_global_step_policies(db: Session = Depends(get_db)):
    return policy.list_policies(db, None)


@router.post(
    "/step-policies",
    response_model=StepPolicySetResult,
    summary="Enable or disable a lifecycle step globally",
    response_description="The stored global policy, plus any cascaded rows and any overriding engagements.",
    operation_id="set_global_step_policy",
    responses={
        404: _NO_STEP,
        409: {
            "model": PolicyOrphansDependentsResponse,
            "description": "Disabling this step would leave a downstream step's required input unsatisfied. "
            "Retry with cascade: true to disable the named dependents in the same request.",
        },
    },
)
def set_global_step_policy(payload: StepPolicyRequest, db: Session = Depends(get_db)):
    # TODO: gate this mutation behind an admin check once auth exists — a
    # global policy change affects every engagement, and the Master Catalog
    # view is already noted as admin-only in a future auth model
    # (04-FRONTEND-SPEC.md, "Future: access control";
    # 23-WORKFLOW-ADMINISTRATION.md Part F).
    """
    Upserts the single global row for `step_name` (`engagement_id IS NULL`).
    Precedence is engagement beats global beats default — an engagement can
    still re-enable a step this disables, and does so unaffected.

    Disabling a step whose non-optional output some other step still relies
    on is refused (`POLICY_ORPHANS_DEPENDENTS`, 409) unless `cascade: true`
    is set, exactly as at the engagement layer — cascaded rows are created
    at this same global layer. On success, `overriding_engagements` lists
    every engagement with its own row re-enabling this step, since a global
    disable never touches those rows — "the admin should know the change is
    partial" (Part A).
    """
    if db.get(models.WfStepRegistration, payload.step_name) is None:
        raise error(404, f"Step '{payload.step_name}' is not registered", field="step_name", code="NOT_FOUND")

    if payload.enabled:
        row = policy.upsert_policy(db, None, payload.step_name, enabled=True, reason=payload.reason, set_by=payload.set_by)
        db.commit()
        db.refresh(row)
        return StepPolicySetResult(policy=StepPolicyOut.model_validate(row))

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

    row = policy.upsert_policy(db, None, payload.step_name, enabled=False, reason=payload.reason, set_by=payload.set_by)

    cascaded_rows = [
        policy.upsert_policy(
            db, None, dependent, enabled=False, reason=f"{policy.CASCADE_REASON_PREFIX}{payload.step_name}", set_by=payload.set_by
        )
        for dependent in outstanding
    ]

    overriding_engagements = policy.find_overriding_engagements(db, payload.step_name)

    db.commit()
    db.refresh(row)
    for cascaded_row in cascaded_rows:
        db.refresh(cascaded_row)

    return StepPolicySetResult(
        policy=StepPolicyOut.model_validate(row),
        cascaded=[StepPolicyOut.model_validate(r) for r in cascaded_rows],
        overriding_engagements=overriding_engagements,
    )


@router.post(
    "/step-policies/validate",
    response_model=StepPolicyValidateResponse,
    summary="Dry-run a global step policy change",
    response_description="What would happen — no row is created or changed either way.",
    operation_id="validate_global_step_policy",
    responses={404: _NO_STEP},
)
def validate_global_step_policy(payload: StepPolicyValidateRequest, db: Session = Depends(get_db)):
    """Same dependency check `POST` runs, without `cascade`, `reason`, or
    any write. `enabled: true` always reports `would_orphan: false`."""
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
    "/step-policies/{step_name}",
    status_code=204,
    summary="Revert a step's global policy to the default (enabled)",
    response_description="Deleted. The step falls through to enabled by default (no engagement row overrides).",
    operation_id="delete_global_step_policy",
    responses={
        404: {"model": ErrorResponse, "description": "No global policy row exists for this step_name."},
        409: {
            "model": PolicyRevertOrphansResponse,
            "description": "This step was disabled globally; reverting would re-enable it globally while a step "
            "it depends on for a required input is still globally disabled. Retry with ?force=true to accept the "
            "orphaned state.",
        },
    },
)
def delete_global_step_policy(
    step_name: str,
    force: bool = Query(default=False, description="Revert even if this step's required input's global producer is still disabled."),
    db: Session = Depends(get_db),
):
    # TODO: gate this mutation behind an admin check once auth exists — see
    # the identical note on set_global_step_policy above.
    """
    Deletes the global row outright. Engagement-level rows are untouched —
    any engagement already overriding this step continues exactly as
    before. Mirrors the engagement-layer DELETE's re-enable guard, checked
    against the global layer alone (`engagement_id=None`): if this step is
    globally disabled and re-enabling it globally would leave it without a
    required input from another step still globally disabled, this is
    refused (`POLICY_REVERT_ORPHANS_STEP`, 409) unless `force=true`.
    """
    row = policy.get_policy(db, None, step_name)
    if row is None:
        raise error(404, f"No global step policy for '{step_name}'", code="NOT_FOUND")

    if not row.enabled and not force:
        blocking = policy.find_blocking_producers(db, None, step_name)
        if blocking:
            raise errors(
                409,
                [
                    {
                        "code": "POLICY_REVERT_ORPHANS_STEP",
                        "message": (
                            f"Re-enabling {step_name} globally would leave it without its required input from "
                            f"{', '.join(blocking)}, still disabled globally."
                        ),
                        "blocking_steps": blocking,
                        "resolution": "Re-enable the blocking step(s) globally first, or retry with ?force=true to accept the orphaned state.",
                    }
                ],
            )

    policy.delete_policy(db, None, step_name)
    db.commit()


@router.get(
    "/effective-policies",
    response_model=list[EffectivePolicyOut],
    summary="The resolved policy state for every in-scope step",
    response_description="Per step appearing in an active job definition: enabled, source, reason, and the raw "
    "global/engagement rows.",
    operation_id="list_effective_step_policies",
)
def list_effective_step_policies(
    engagement_id: str | None = Query(
        default=None, description="Resolve engagement-vs-global-vs-default. Omit to resolve global-vs-default only."
    ),
    db: Session = Depends(get_db),
):
    """
    Precedence: engagement beats global beats default. Only steps that
    appear in at least one active job definition are included — the other
    steps have no policy meaning yet (23-WORKFLOW-ADMINISTRATION.md Part B).
    """
    if engagement_id is not None and db.get(models.Engagement, engagement_id) is None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")

    step_names = policy.in_scope_step_names(db)
    resolved = policy.resolve_effective_policies(db, engagement_id, step_names)

    return [
        EffectivePolicyOut(
            step_name=name,
            enabled=effective.enabled,
            source=effective.source,
            reason=effective.reason,
            global_policy=StepPolicyOut.model_validate(effective.global_policy) if effective.global_policy else None,
            engagement_policy=StepPolicyOut.model_validate(effective.engagement_policy) if effective.engagement_policy else None,
        )
        for name, effective in resolved.items()
    ]


@router.get(
    "/policy-matrix",
    response_model=PolicyMatrixOut,
    summary="Steps x engagements policy overview",
    response_description="Every in-scope step's global state and every engagement's effective state for it.",
    operation_id="get_policy_matrix",
)
def get_policy_matrix(db: Session = Depends(get_db)):
    """
    The master-view overview: one row per step appearing in an active job
    definition, showing the global state and, per engagement, the resolved
    effective state — so a deviation from default is visible without
    opening each engagement individually.
    """
    step_names = policy.in_scope_step_names(db)
    engagements = db.query(models.Engagement).order_by(models.Engagement.id).all()

    registrations = {
        row.step_name: row
        for row in db.query(models.WfStepRegistration).filter(models.WfStepRegistration.step_name.in_(step_names))
    }

    global_effective = policy.resolve_effective_policies(db, None, step_names)
    per_engagement_effective = {
        engagement.id: policy.resolve_effective_policies(db, engagement.id, step_names) for engagement in engagements
    }

    steps_out = []
    for name in step_names:
        reg = registrations.get(name)
        global_state = global_effective[name]
        steps_out.append(
            PolicyMatrixStepOut(
                step_name=name,
                lifecycle_step_no=reg.lifecycle_step_no if reg else None,
                display_name=reg.display_name if reg else name,
                implementation_status=reg.implementation_status if reg else "",
                # "global" is a Python keyword, so the model exposes this as
                # `global_state` (alias "global") and populate_by_name=True
                # lets us construct it by the plain attribute name here.
                global_state=PolicyStateOut(
                    enabled=global_state.enabled, source=global_state.source, reason=global_state.reason
                ),
                engagements={
                    engagement.id: PolicyStateOut(
                        enabled=(state := per_engagement_effective[engagement.id][name]).enabled,
                        source=state.source,
                        reason=state.reason,
                    )
                    for engagement in engagements
                },
            )
        )

    return PolicyMatrixOut(
        engagements=[PolicyMatrixEngagementOut(id=e.id, client_name=e.client_name) for e in engagements],
        steps=steps_out,
    )
