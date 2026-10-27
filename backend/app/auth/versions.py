"""Edits to shared records carry a version check: decisions, item decisions, catalog items (edit_version) and their
resolutions, engagement settings, and matrix confirmations (by the confirmation's id). The caller names the version of
the copy it edited in an If-Match header (0 when the record did not exist yet); the row is locked, its version
compared, and an edit made from a stale copy is refused (409 STALE_COPY), saying who changed it first. Nothing is
overwritten. The version goes up by one with each edit.

An edit that does not say which version it changes is refused too (428 VERSION_REQUIRED): without it, a stale copy
could not be told from a current one. The UI sends the version it shows; command-line tools read the current version
and send it (python -m app.engine.allowlist).

Explicitly unversioned, and why each is safe without one:
- creating a record: a catalog item, a resolution, a pattern or target state, an engagement, a matrix confirmation (a
  second confirmation of an entry already confirmed is refused, naming who confirmed it), a user;
- a catalog item's or resolution's delete, restore and make-default: state changes guarded by their own checks
  (deleting what is deleted, or a default that must stay, is refused), each bumping the item's edit_version so any
  copy made before them is stale;
- an engagement's hard deletion (the name must be typed) and repository changes (owner-only, not shared records);
- the platform's own writes: the seed and catalog import (app.items.baseline, which never overwrites an edit),
  derived decisions (app.items.coupling), readiness and impact staleness, migrations.
"""
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
    """Refuses an edit that names no version (428), or one made from a stale copy (409). `current_version` None means
    the record does not exist (yet); a copy of version 0 is a copy made when it did not."""
    wanted = expected(if_match)
    if wanted is None:
        raise error(428, f"Not saved: the edit does not say which version of {what} it changes. Send the version you "
                         "loaded in If-Match (0 when there was none yet), so an edit made from a stale copy can be "
                         "refused.", field="If-Match", code="VERSION_REQUIRED")
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
