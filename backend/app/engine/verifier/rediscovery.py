"""Re-discovery (36-COPILOT-ENHANCED-CONVERSION Part E): run the platform's own per-repository discovery on a
scratch worktree of a branch, exactly as on any registered repository, and keep what it found.

The worktree is registered as a repository in the same engagement — so impact analysis reads the same
decisions — under a name that says what it is, discovery runs in-process through `impact-analysis`, the
results are read into a snapshot, and the repository is soft-deleted again so it never appears in the
engagement's views. Its rows stay, as with any soft-deleted repository.
"""
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app import models
from app.conversion import planner
from app.engine.inputs.collect import collect
from app.repositories import service as repositories
from app.repositories.schemas import RegisterLocalPathRequest
from app.workflow.runtime import service as runtime

JOB = "phase0-repository-discovery"
REGISTERED_BY = "app.engine.verifier"


class RediscoveryFailed(RuntimeError):
    pass


def snapshot(db: Session, engagement_id: str, worktree: Path, name: str) -> dict:
    engagement = db.get(models.Engagement, engagement_id)
    repository = repositories.register_local_path(db, engagement, RegisterLocalPathRequest(
        source_type="local_path", local_path=str(worktree), name=name))
    db.commit()
    repository_id = repository.id
    try:
        execution = runtime.launch_job(db, JOB, {"engagement_id": engagement_id, "repository_id": str(repository.id),
                                                 "ingest_token": repository.ingest_token or str(uuid.uuid4())},
                                       triggered_by="manual")
        db.commit()
        steps = {s.step_name: s.exit_status for s in runtime.get_step_executions(db, execution.id)}
        if execution.batch_status != "COMPLETED":
            raise RediscoveryFailed(f"discovery on {worktree} ended {execution.batch_status}/{execution.exit_status}: {steps}")
        db.refresh(repository)
        model = collect(db, repository)
        try:
            unit_tests = planner._unit_test_projects(db, repository.id)
            solution = planner._solution(db, repository.id, unit_tests)
        except (LookupError, ValueError) as err:
            unit_tests, solution = [], None
            model["test_projects_problem"] = str(err)
        return {"repository_id": str(repository.id), "execution_id": str(execution.id), "steps": steps,
                "model": model, "unit_test_projects": unit_tests, "solution": solution}
    finally:
        db.rollback()                      # a failure above may have left the session unusable
        repository = db.get(models.Repository, repository_id)
        if repository is not None and repository.deleted_at is None:
            repositories.soft_delete(repository, REGISTERED_BY)
            db.commit()


def work_items(model: dict) -> dict[tuple[str, str], dict]:
    """{(project, item): {occurrences: n, places: [file:line ...]}} — a work item is a found (project, item)."""
    out: dict[tuple[str, str], dict] = {}
    for item in model["items"]:
        for occ in item["occurrences"]:
            entry = out.setdefault((occ["project"], item["id"]), {"occurrences": 0, "places": []})
            entry["occurrences"] += 1
            for line in occ["lines"] or [None]:
                place = (occ["file"] or occ["project"]) + (f":{line['line']}" if line else "")
                if place not in entry["places"]:
                    entry["places"].append(place)
    return out
