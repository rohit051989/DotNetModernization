"""The checks every text written for a conversion engine passes when it is saved (36-COPILOT-ENHANCED-CONVERSION Part K
and "Engagement guidance"): a resolution's master guidance, an engagement's note on a resolution, an engagement's
conventions. The engine reads only the repository's branch, so the text must be self-contained (no platform document,
path, step or id: app.engine.inputs.selfcontained), and it must hold no secret value (app.engine.inputs.secrets). A
failure is refused as a field error when it is saved, not found later by every preparation that would use it."""
from sqlalchemy.orm import Session

from app.errors import error


def check(db: Session, field: str, text: str | None, what: str) -> None:
    """Raises a 422 field error on `field` when `text` is not self-contained or holds a secret value. Empty passes."""
    if not (text or "").strip():
        return
    from app.engine.inputs import secrets, selfcontained

    loose = selfcontained.check({field: text}, selfcontained.vocabulary(db))
    if loose:
        named = "; ".join(f"line {f['line']}: {f['check']} ({f['match']})" for f in loose[:5])
        raise error(422, f"The {what} must be self-contained: the engine reads only the repository's branch. "
                         f"Found {len(loose)}: {named}.", field=field, code="NOT_SELF_CONTAINED")
    found = secrets.check({field: text}, None, set())
    if found:
        named = "; ".join(f"{f['detail']}: {f['check']}" for f in found[:5])
        raise error(422, f"The {what} must not hold a secret value (a password, key, token or connection string): name "
                         f"the setting that holds it instead. Found {len(found)}: {named}.", field=field,
                    code="SECRET_VALUE")
