"""Items an engagement decided are not applicable (28-ITEM-AND-CONVERSION-MODEL.md Part F, "Not applicable").

A decision's outcome is `resolve` (it chooses a resolution) or `not_applicable` (the item does not apply to this
engagement). Only an approved, live not-applicable decision takes effect. Its item's findings are kept: discovery still
detects them, and the work list shows them marked "not applicable for this engagement", counted apart from open work.
It is no work: nothing about it goes into either engine's conversion inputs (app.engine.inputs.collect), the verifier
does not count it as remaining, and impact-analysis computes no impact for it. Superseding the decision, or moving it
back to `resolve`, brings the item back with no rescan: the findings were never dropped.

The master catalog is never touched (CLAUDE.md rule 9): this is engagement data.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

RESOLVE = "resolve"
NOT_APPLICABLE = "not_applicable"
OUTCOMES = (RESOLVE, NOT_APPLICABLE)
LABEL = "not applicable for this engagement"


def not_applicable(db: Session, engagement_id: str | None) -> dict[str, dict]:
    """{item_id: {approver, date, rationale}} for each approved, live not-applicable decision of the engagement."""
    if not engagement_id:
        return {}
    rows = db.execute(text("""
        SELECT item_id, approver_name, decision_date, rationale FROM engagement_decisions
        WHERE engagement_id = :e AND status = 'approved' AND outcome = :na
        ORDER BY item_id"""), {"e": engagement_id, "na": NOT_APPLICABLE})
    return {item_id: {"approver": approver, "date": date.isoformat() if date else None, "rationale": rationale}
            for item_id, approver, date, rationale in rows}
