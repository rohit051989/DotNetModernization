"""independent-verification (17-LIFECYCLE-STEPS.md; 36-COPILOT-ENHANCED-CONVERSION.md Parts E and N): the conversion
verifier as a workflow step, the only step of the job `conversion-verification`. A person starts it from the
repository's Conversion section, for a conversion that has been run.

It verifies the conversion's branch against its baseline (app.engine.convert.verify), independent of the engine,
and writes VERIFICATION.md and verification.json into `<RUNS_DIR>/<engagement>/<repository>/verification/
conversion-<n>/`, which the Conversion section shows. The step completes with the verdict in its message; it fails
only when the verification could not be made.

Parameters: `repository_id`, `conversion` (the conversion's number).
"""
import json
import sys

from sqlalchemy.orm import sessionmaker

from app import models
from app.db import make_engine
from app.workflow.contract import StepContext, StepResult


def run(context: StepContext) -> StepResult:
    from app.engine import convert

    params = context.parameters
    repository_id, number = params.get("repository_id"), params.get("conversion")
    if not repository_id or not number or not context.database_url:
        return StepResult(exit_status="FAILED", exit_message="repository_id and conversion are required")
    engine = make_engine(context.database_url)
    db = sessionmaker(bind=engine)()
    try:
        repository = db.get(models.Repository, repository_id)
        if repository is None:
            return StepResult(exit_status="FAILED", exit_message=f"repository '{repository_id}' does not exist")
        record = convert.record(repository.engagement_id, repository.slug, int(number))
        if record is None:
            return StepResult(exit_status="FAILED", exit_message=f"{repository.slug} has no conversion {number}")
        refusal = convert.verify_refusal(record)
        if refusal:
            return StepResult(exit_status="FAILED", exit_message=refusal)
        report = convert.verify(db, repository.engagement_id, repository.slug, record["branch"])
        return StepResult(exit_status="COMPLETED",
                          exit_message=f"{report['label']}: {report['verdict']}"
                          + "".join(f"; {r}" for r in report["reasons"][:3]))
    except Exception as error:
        return StepResult(exit_status="FAILED", exit_message=f"verification could not be made: {type(error).__name__}: {error}"[:2000])
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    _context = StepContext.model_validate(json.load(sys.stdin))
    try:
        _result = run(_context)
    except Exception as exc:  # a "process"-style invocation must still emit valid JSON
        _result = StepResult(exit_status="FAILED", exit_message=f"{type(exc).__name__}: {exc}")
    sys.stdout.write(_result.model_dump_json())
