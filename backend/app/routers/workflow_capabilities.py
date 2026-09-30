from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.workflow.schemas import MetricsAvailable, WorkflowCapabilities

router = APIRouter(prefix="/api/workflow", tags=["Workflow Steps"])

# metric name -> the step_name whose implementation_status governs it.
_METRIC_STEP = {
    "repository_count": "repository-ingest",
    "application_count": "application-fingerprinting",
    # The work list is the impact map: retired impact-map-generation's metric
    # is item-detection's (17-LIFECYCLE-STEPS.md v2.0).
    "item_detection": "item-detection",
    "test_coverage": "test-coverage-assessment",
    "risk_tier": "risk-scoring-tier-assignment",
}


@router.get(
    "/capabilities",
    response_model=WorkflowCapabilities,
    summary="Get which lifecycle steps are implemented",
    response_description="Implemented step names, and which dashboard metrics they unlock.",
    operation_id="get_workflow_capabilities",
)
def get_workflow_capabilities(db: Session = Depends(get_db)):
    """
    Derived from `wf_step_registrations.implementation_status`, fetched once
    by the frontend on load. Renders `—` with an explanatory tooltip for any
    metric whose producing step is still a stub — never a fabricated zero.
    See 15-REPOSITORY-INGEST-UI.md Part G.
    """
    implemented = {
        row.step_name: row
        for row in db.query(models.WfStepRegistration).filter(
            models.WfStepRegistration.implementation_status == "implemented"
        )
    }
    implemented_steps = sorted(
        implemented.keys(), key=lambda name: (implemented[name].lifecycle_step_no or 0)
    )
    return WorkflowCapabilities(
        implemented_steps=implemented_steps,
        metrics_available=MetricsAvailable(
            **{metric: step_name in implemented for metric, step_name in _METRIC_STEP.items()}
        ),
    )
