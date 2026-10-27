"""Edits to shared records carry a version check: decisions, item decisions, catalog items, engagement settings, and
matrix confirmations (by the confirmation's id). The UI sends the version of the copy it shows in an If-Match
header; the row is locked, its version compared, and an edit made from a stale copy is refused (409 STALE_COPY),
saying who changed it first. Nothing is overwritten. The version goes up by one with each edit.

A caller that sends no If-Match (a script, a test calling the route function) is not checked: the UI always sends
it."""
from sqlalchemy.orm import Session

from app.auth import activity
from app.errors import error


def expected(if_match: str | None) -> int | None:
    """The version an If-Match header names: 3, "3" or W/"3". None when absent; 422 when it is not a number."""
    if if_match is None or not str(if_match).strip():
        return None
    value = str(if_match).strip()
    if value.startswith("W/"):
        value = value[2:]
    value = value.strip('"')
    try:
        return int(value)
    except ValueError:
        raise error(422, f"If-Match must be the version of the copy being edited, not '{if_match}'.",
                    field="If-Match", code="INVALID_VERSION") from None


def locked(db: Session, model, key):
    """The row, locked until the transaction ends, so two edits from the same version cannot both pass the check."""
    return db.get(model, key, with_for_update=True)


def check(db: Session, current_version: int | None, if_match: str | None, subject_type: str, subject_id,
          what: str) -> None:
    """Refuses an edit made from a stale copy. `current_version` None means the record does not exist (yet); a copy
    of version 0 is a copy made when it did not."""
    wanted = expected(if_match)
    if wanted is None:
        return
    have = current_version or 0
    if wanted == have:
        return
    if have == 0:
        said = f"{what} you edited has been removed since you loaded it"
    elif wanted == 0:
        said = f"someone else created {what} first ({activity.describe(activity.last(db, subject_type, subject_id))})"
    else:
        said = (f"someone else changed {what} first ({activity.describe(activity.last(db, subject_type, subject_id))}), "
                f"after the copy you edited (version {wanted}; it is now version {have})")
    raise error(409, f"Not saved: {said}. Nothing was overwritten. Reload to see the current version, then make your "
                     "change again.", code="STALE_COPY")
