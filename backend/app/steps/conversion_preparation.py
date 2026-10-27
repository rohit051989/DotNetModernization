"""conversion-preparation (17-LIFECYCLE-STEPS.md; 36-COPILOT-ENHANCED-CONVERSION.md Part N): the last step of the
per-repository discovery job. It prepares the repository's conversion for an engine with no command run by hand:
the branch and worktree, the package step, the engine's inputs under .github, and the runbook (app.engine.convert).

- A conversion starts from the commit this discovery run scanned.
- A rescan refreshes a conversion that has not been run yet (no commits beyond its inputs), in place, onto that
  commit. A conversion that has been run is left as it is; a person starts the next one from the UI, which runs this
  job with `new_conversion`: always a new conversion, no existing one changed.
- A baseline that does not build or pass its tests still gets a conversion: the package step is skipped, the reason
  recorded, and the package changes go to the engine as instructions.
- Package lookups were answered by this run's dependency-assessment, so their age is not checked again.
- It never fails the discovery run. Whatever happens is recorded in `<RUNS_DIR>/<engagement>/<repository>/
  conversions/last-prepare.json`, which the Conversion section shows, and the step completes.

Parameters: `prepare_conversion` (default true; the verifier's isolated re-discovery sets false), `new_conversion`
(default false).
"""
import datetime
import json
import sys
import traceback

from sqlalchemy.orm import sessionmaker

from app import models
from app.db import make_engine
from app.results import conversions as shared_conversions
from app.workflow.contract import StepContext, StepResult

LAST_PREPARE = "last-prepare.json"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def record_attempt(engagement_id: str, slug: str, attempt: dict) -> None:
    from app.engine import convert

    home = convert.conversions_dir(engagement_id, slug)
    home.mkdir(parents=True, exist_ok=True)
    (home / LAST_PREPARE).write_text(json.dumps(attempt, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def run(context: StepContext) -> StepResult:
    params = context.parameters
    if params.get("prepare_conversion", True) in (False, "false", "False", 0):
        return StepResult(exit_status="NOOP", exit_message="not asked to prepare a conversion (prepare_conversion=false)")
    repository_id = params.get("repository_id")
    if not repository_id or not context.database_url:
        return StepResult(exit_status="NOOP", exit_message="no repository or database: nothing to prepare")

    from app.engine import convert

    engine = make_engine(context.database_url)
    db = sessionmaker(bind=engine)()
    attempt = {"at": _now(), "jobExecutionId": context.job_execution_id, "newConversion": bool(params.get("new_conversion"))}
    repository = None
    try:
        repository = db.get(models.Repository, repository_id)
        if repository is None:
            return StepResult(exit_status="NOOP", exit_message=f"repository '{repository_id}' does not exist")
        result = convert.prepare(db, repository.engagement_id, repository.slug,
                                 when_run="next" if params.get("new_conversion") in (True, "true", "True", 1) else "keep",
                                 lookups_from_discovery=True)
        step = result.get("packageStep") or {}
        attempt.update(status=result["action"], number=result.get("number"), branch=result.get("branch"),
                       message=result.get("reason") or (
                           f"conversion {result['number']} {result['action']}: {result['branch']} from "
                           f"{result['baseline'][:8]} ({result['baselineFrom']}) at {result['head'][:8]}"
                           + (f"; package step skipped: {step['skipped']}" if step.get("skipped") else
                              f"; package step {step.get('cycles', 0)} cycle(s)" if result["action"] != "kept" else "")))
        record_attempt(repository.engagement_id, repository.slug, attempt)
        shared_conversions.publish_after_step(db, repository)
        return StepResult(exit_status="COMPLETED", exit_message=attempt["message"])
    except Exception as error:   # never fails the discovery run: recorded, and the step completes
        db.rollback()
        attempt.update(status="failed", message=f"{type(error).__name__}: {error}",
                       detail=traceback.format_exc(limit=8))
        if repository is not None:
            try:
                record_attempt(repository.engagement_id, repository.slug, attempt)
            except OSError:
                pass
            shared_conversions.publish_after_step(db, repository)
        return StepResult(exit_status="COMPLETED", exit_message=f"conversion not prepared: {attempt['message']}"[:2000])
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    _context = StepContext.model_validate(json.load(sys.stdin))
    try:
        _result = run(_context)
    except Exception as exc:  # a "process"-style invocation must still emit valid JSON
        _result = StepResult(exit_status="COMPLETED", exit_message=f"conversion not prepared: {type(exc).__name__}: {exc}")
    sys.stdout.write(_result.model_dump_json())
