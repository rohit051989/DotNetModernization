"""Whether a repository's latest discovery run failed, and which steps' results are older because of it.

When a discovery run stops at a failed step, the steps before it stored new results and the failed step and every step
after it did not: each of those keeps showing the results of an earlier run. The repository page says so, in its
header and on each tab those steps feed (04-FRONTEND-SPEC.md "Repository page"), and conversion preparation refuses to
run on such a mix (app.engine.convert). Read from the database only, so it is the same on every machine.
"""
import datetime
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.workflow.definition.model import DecisionNode, JobDefinitionFile, SplitNode, StepNode
from app.workflow.runtime import service as runtime

DISCOVERY = "phase0-repository-discovery"
ENDED_BADLY = ("FAILED", "STOPPED", "ABANDONED")
STEP_FAILED = ("FAILED", "TIMED_OUT", "STALLED")


def _steps(nodes) -> list[str]:
    """Every step a flow names, in order (both sides of a split or a decision)."""
    names: list[str] = []
    for node in nodes:
        if isinstance(node, StepNode):
            names.append(node.step)
        elif isinstance(node, SplitNode):
            for branch in node.branches:
                names += _steps(branch)
        elif isinstance(node, DecisionNode):
            for outcome in node.outcomes.values():
                names += _steps(outcome)
            names += _steps(node.default or [])
    return list(dict.fromkeys(names))


def _short(message: str | None) -> str | None:
    """The first line of a step's message, short enough for a notice. The full text is on the Activity tab."""
    if not message:
        return None
    first = next((line.strip() for line in message.splitlines() if line.strip()), "")
    return first[:300] or None


def results_dates(db: Session, repository_id: uuid.UUID, steps: list[str]) -> dict[str, datetime.datetime | None]:
    """For each step, when it last completed for this repository in a discovery run: the date of the results its views
    show. None when it never has."""
    if not steps:
        return {}
    rows = db.execute(text("""
        select s.step_name, max(s.ended_at) as ended_at
        from wf_step_executions s
        join wf_job_executions j on j.id = s.job_execution_id
        join wf_job_instances i on i.id = j.job_instance_id
        where i.job_name = :job and i.parameters->>'repository_id' = :r
          and s.step_name = any(:steps) and s.batch_status = 'COMPLETED'
          and coalesce(s.exit_status, '') <> all(:failed)
        group by s.step_name
    """), {"job": DISCOVERY, "r": str(repository_id), "steps": steps, "failed": list(STEP_FAILED)}).all()
    found = {r.step_name: r.ended_at for r in rows}
    return {step: found.get(step) for step in steps}


def failed_scan(db: Session, repository_id: uuid.UUID) -> dict | None:
    """The repository's latest discovery run, when it ended without completing (or a step of it failed): when, at which
    step, the step's message, and for each step that did not complete in it the date of the results shown instead.
    None when the latest run completed, is still running with nothing failed, or there is none."""
    latest = runtime.list_executions(db, job_name=DISCOVERY, repository_id=str(repository_id), limit=1)
    if not latest:
        return None
    execution = latest[0]
    steps = runtime.get_step_executions(db, execution.id)
    failed = [s for s in steps if s.batch_status in ENDED_BADLY or s.exit_status in STEP_FAILED]
    if execution.batch_status not in ENDED_BADLY and not failed:
        return None
    definition_row = db.get(models.WfJobDefinition, execution.job_definition_id)
    flow = _steps(JobDefinitionFile.model_validate(definition_row.definition).flow) if definition_row else []
    done = {s.step_name for s in steps if s.batch_status == "COMPLETED" and s.exit_status not in STEP_FAILED}
    not_completed = [step for step in flow if step not in done]
    first = failed[0] if failed else None
    return {
        "job_execution_id": execution.id,
        "status": execution.batch_status,
        "failed_step": first.step_name if first else None,
        "message": _short((first.exit_message if first else None) or execution.exit_message),
        "at": (first.ended_at if first else None) or execution.ended_at or execution.started_at or execution.created_at,
        "results_from": results_dates(db, repository_id, not_completed),
    }


def refusal(db: Session, repository_id: uuid.UUID) -> str | None:
    """Why a conversion must not be prepared now, or None: the latest discovery run failed, so some steps' results are
    from this run and others from an earlier one, about different commits."""
    failed = failed_scan(db, repository_id)
    if failed is None:
        return None
    where = f"at {failed['failed_step']}" if failed["failed_step"] else f"({failed['status'].lower()})"
    older = ", ".join(step for step in failed["results_from"] if step != "conversion-preparation") or "no step"
    at = failed["at"].astimezone(datetime.timezone.utc) if failed["at"].tzinfo else failed["at"]
    return (f"The latest discovery run failed {where} on {at:%Y-%m-%d %H:%M} UTC, so the results of {older} "
            "are from an earlier run while the others are new. A conversion is not prepared on a mix of new and older "
            "results: fix the failure and rescan the repository first (its Activity tab has the failure).")
