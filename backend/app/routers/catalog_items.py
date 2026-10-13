"""Master catalog items and their resolutions —
28-ITEM-AND-CONVERSION-MODEL.md Parts D, E and F.

Client-agnostic. Engagement decisions live in item_decisions.py and never
write here. Deprecate (`status: deprecated`, via PUT) and soft delete
(`DELETE`, reversible with `restore`) are distinct mechanisms, per CLAUDE.md
rule 7; nothing is hard-deleted.
"""

import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.items import readiness, signal_index
from app.items import schemas as item_schemas
from app.items.detection import validate_detection

router = APIRouter(prefix="/api/catalog/items", tags=["Item Catalog"])

_ITEM_NOT_FOUND = {"model": ErrorResponse, "description": "No catalog item exists with this id."}
_INVALID_DETECTION = {"model": ErrorResponse, "description": "The detection fails a Part E rule for this item's scope."}


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _get_item(db: Session, item_id: str, include_deleted: bool = False) -> models.CatalogItem:
    item = db.get(models.CatalogItem, item_id)
    if item is None or (item.deleted_at is not None and not include_deleted):
        raise error(404, f"Catalog item '{item_id}' not found", code="NOT_FOUND")
    return item


def _registered_evidence_kinds(db: Session) -> dict[str, str]:
    return {row.name: row.evidence_kind for row in db.query(models.SignalRegistryEntry)}


def _live_decision_count(db: Session, **filters) -> int:
    query = db.query(models.EngagementDecision).filter(models.EngagementDecision.status != "superseded")
    for column, value in filters.items():
        query = query.filter(getattr(models.EngagementDecision, column) == value)
    return query.count()


def _apply_item_fields(item: models.CatalogItem, payload: item_schemas.CatalogItemWrite, detection: dict) -> bool:
    """Returns True if detection changed (a version bump)."""
    detection_changed = item.detection != detection or item.scope != payload.scope
    item.name = payload.name
    item.description = payload.description
    item.scope = payload.scope
    item.category = payload.category
    item.detection = detection
    item.excluded_roles = sorted(set(payload.excluded_roles))
    item.owner_team = payload.owner_team
    item.status = payload.status
    if "engine_guidance" in payload.model_fields_set:   # omitted: unchanged (a client unaware of it never wipes it)
        item.engine_guidance = payload.engine_guidance
    item.updated_at = _now()
    return detection_changed


# ---------- items ----------


@router.get(
    "",
    response_model=list[item_schemas.CatalogItemOut],
    summary="List catalog items",
    operation_id="list_catalog_items",
)
def list_items(
    state: item_schemas.ReadinessState | None = Query(None, description="Filter by computed readiness."),
    scope: item_schemas.ItemScope | None = Query(None),
    status: item_schemas.ItemStatus | None = Query(None, description="Lifecycle status; deprecated items are included unless filtered."),
    include_deleted: bool = Query(False, description="Include soft-deleted items."),
    db: Session = Depends(get_db),
):
    query = db.query(models.CatalogItem)
    if not include_deleted:
        query = query.filter(models.CatalogItem.deleted_at.is_(None))
    if state is not None:
        query = query.filter(models.CatalogItem.state == state)
    if scope is not None:
        query = query.filter(models.CatalogItem.scope == scope)
    if status is not None:
        query = query.filter(models.CatalogItem.status == status)
    return query.order_by(models.CatalogItem.id).all()


@router.get(
    "/{item_id}",
    response_model=item_schemas.CatalogItemOut,
    summary="Get a catalog item",
    operation_id="get_catalog_item",
    responses={404: _ITEM_NOT_FOUND},
)
def get_item(
    item_id: str,
    include_deleted: bool = Query(False, description="Return the item even if soft-deleted."),
    db: Session = Depends(get_db),
):
    return _get_item(db, item_id, include_deleted)


@router.get(
    "/{item_id}/signals",
    response_model=list[item_schemas.ItemSignal],
    summary="The signals an item's detection references",
    operation_id="list_catalog_item_signals",
    responses={404: _ITEM_NOT_FOUND},
)
def list_item_signals(item_id: str, db: Session = Depends(get_db)):
    """The reverse of GET /api/catalog/signal-index: this item's signals,
    each with its usage (match / none / occurrence_source) and state."""
    return signal_index.item_signals(db, _get_item(db, item_id))


@router.post(
    "",
    response_model=item_schemas.CatalogItemWriteResult,
    status_code=201,
    summary="Create a catalog item",
    response_description="The item with its computed readiness, plus non-blocking warnings.",
    operation_id="create_catalog_item",
    responses={409: {"model": ErrorResponse, "description": "An item with this id already exists."}, 422: _INVALID_DETECTION},
)
def create_item(payload: item_schemas.CatalogItemCreate, db: Session = Depends(get_db)):
    """
    `state` and `state_reason` are computed from the detection's signals and
    cannot be supplied. An item referencing a signal that is not registered
    yet is accepted, computed `not_ready`, and never evaluated by detection
    until that signal exists and its extractor is implemented.
    """
    # TODO: gate behind an admin role once auth exists.
    if db.get(models.CatalogItem, payload.id) is not None:
        raise error(409, f"Catalog item '{payload.id}' already exists", code="DUPLICATE_ID")
    detection, warnings = validate_detection(payload.scope, payload.detection, _registered_evidence_kinds(db))

    item = models.CatalogItem(id=payload.id, version=1)
    _apply_item_fields(item, payload, detection)
    db.add(item)
    readiness.recompute_item(db, item)
    db.commit()
    db.refresh(item)
    return item_schemas.CatalogItemWriteResult(item=item, warnings=warnings)


@router.put(
    "/{item_id}",
    response_model=item_schemas.CatalogItemWriteResult,
    summary="Replace a catalog item",
    operation_id="update_catalog_item",
    responses={404: _ITEM_NOT_FOUND, 422: _INVALID_DETECTION},
)
def update_item(item_id: str, payload: item_schemas.CatalogItemWrite, db: Session = Depends(get_db)):
    """Full replace. `version` is bumped when detection or scope changes.
    Setting `status: deprecated` retires the item from the master catalog
    for every engagement while keeping it visible and its decisions
    resolvable; that is not the same as soft delete."""
    # TODO: gate behind an admin role once auth exists.
    item = _get_item(db, item_id)
    detection, warnings = validate_detection(payload.scope, payload.detection, _registered_evidence_kinds(db))
    if _apply_item_fields(item, payload, detection):
        item.version += 1
    readiness.recompute_item(db, item)
    db.commit()
    db.refresh(item)
    return item_schemas.CatalogItemWriteResult(item=item, warnings=warnings)


@router.delete(
    "/{item_id}",
    response_model=item_schemas.SoftDeleteResponse,
    summary="Soft-delete a catalog item",
    operation_id="delete_catalog_item",
    responses={
        404: _ITEM_NOT_FOUND,
        409: {"model": ErrorResponse, "description": "Live engagement decisions still reference this item."},
    },
)
def delete_item(
    item_id: str,
    deleted_by: str | None = Query(None, description="Free-text identity performing the delete; there is no auth system yet."),
    db: Session = Depends(get_db),
):
    """Hides the item and its resolutions everywhere until restored.
    Blocked while any engagement holds a non-superseded decision on it."""
    # TODO: gate behind an admin role once auth exists.
    item = _get_item(db, item_id)
    live = _live_decision_count(db, item_id=item_id)
    if live:
        raise error(
            409,
            f"Catalog item '{item_id}' is referenced by {live} non-superseded engagement decision(s); supersede them first.",
            code="REFERENCED_BY_DECISIONS",
        )
    item.deleted_at = _now()
    item.deleted_by = deleted_by
    (
        db.query(models.ItemResolution)
        .filter(models.ItemResolution.item_id == item_id, models.ItemResolution.deleted_at.is_(None))
        .update({"deleted_at": item.deleted_at, "deleted_by": deleted_by}, synchronize_session=False)
    )
    db.commit()
    return item_schemas.SoftDeleteResponse(id=item.id, deleted_at=item.deleted_at)


@router.post(
    "/{item_id}/restore",
    response_model=item_schemas.SoftDeleteResponse,
    summary="Restore a soft-deleted catalog item",
    operation_id="restore_catalog_item",
    responses={404: _ITEM_NOT_FOUND},
)
def restore_item(item_id: str, db: Session = Depends(get_db)):
    """Clears deleted_at on the item only. Its resolutions stay deleted
    until restored one by one, since some may have been deleted on purpose
    before the item was."""
    # TODO: gate behind an admin role once auth exists.
    item = _get_item(db, item_id, include_deleted=True)
    item.deleted_at = None
    item.deleted_by = None
    item.updated_at = _now()
    db.commit()
    return item_schemas.SoftDeleteResponse(id=item.id, deleted_at=None)


# ---------- resolutions ----------


def _check_default_unique(db: Session, item_id: str, resolution_id: str, is_default: bool) -> None:
    if not is_default:
        return
    other = (
        db.query(models.ItemResolution)
        .filter(
            models.ItemResolution.item_id == item_id,
            models.ItemResolution.is_default.is_(True),
            models.ItemResolution.deleted_at.is_(None),
            models.ItemResolution.id != resolution_id,
        )
        .first()
    )
    if other is not None:
        raise error(
            409,
            f"Resolution '{other.id}' is already the default for item '{item_id}'; unset it first.",
            code="DEFAULT_ALREADY_SET",
        )


def _live_default(db: Session, item_id: str, excluding: str | None = None) -> models.ItemResolution | None:
    query = db.query(models.ItemResolution).filter(
        models.ItemResolution.item_id == item_id,
        models.ItemResolution.is_default.is_(True),
        models.ItemResolution.deleted_at.is_(None),
    )
    if excluding is not None:
        query = query.filter(models.ItemResolution.id != excluding)
    return query.first()


def _other_live_active(db: Session, item_id: str, resolution_id: str) -> int:
    return (
        db.query(models.ItemResolution)
        .filter(
            models.ItemResolution.item_id == item_id,
            models.ItemResolution.id != resolution_id,
            models.ItemResolution.deleted_at.is_(None),
            models.ItemResolution.status == "active",
        )
        .count()
    )


def _check_default_stays(db: Session, resolution: models.ItemResolution, *, unset: bool, deactivate: bool, remove: bool) -> None:
    """Every active item has exactly one default (app/items/defaults.py). The
    default cannot be unset, deprecated or deleted while the item has another
    live resolution: move the default first (make-default), so the item is
    never without one. The item's last resolution can go."""
    if not resolution.is_default or not (unset or deactivate or remove):
        return
    if _other_live_active(db, resolution.item_id, resolution.id) == 0 and not (unset or deactivate):
        return
    what = "deleted" if remove else "deprecated" if deactivate else "unset as the default"
    raise error(
        409,
        f"Resolution '{resolution.id}' is the default for item '{resolution.item_id}' and cannot be {what}: "
        "every item has exactly one default. Make another resolution the default first.",
        code="DEFAULT_REQUIRED",
    )


def _check_name_unique(db: Session, item_id: str, resolution_id: str, name: str) -> None:
    clash = (
        db.query(models.ItemResolution)
        .filter(
            models.ItemResolution.item_id == item_id,
            models.ItemResolution.name == name,
            models.ItemResolution.id != resolution_id,
        )
        .first()
    )
    if clash is not None:
        raise error(409, f"Item '{item_id}' already has a resolution named '{name}'", code="DUPLICATE_NAME")


def _resolution_out(db: Session, resolution: models.ItemResolution) -> item_schemas.ResolutionOut:
    """The resolution with what choosing it derives for dependent items
    (resolution_derivations, 28-ITEM Part U), shown beside it."""
    rows = (
        db.query(models.ResolutionDerivation)
        .filter(models.ResolutionDerivation.resolution_id == resolution.id, models.ResolutionDerivation.deleted_at.is_(None))
        .order_by(models.ResolutionDerivation.dependent_item_id)
        .all()
    )
    return item_schemas.ResolutionOut.model_validate(resolution).model_copy(
        update={"derivations": [item_schemas.DerivationOut.model_validate(row) for row in rows]})


def _apply_resolution_fields(resolution: models.ItemResolution, payload: item_schemas.ResolutionWrite) -> None:
    for field in (
        "name",
        "description",
        "target_description",
        "consumer_impact",
        "effort",
        "is_default",
        "linux_compatible",
        "container_ready",
        "notes",
        "status",
    ):
        setattr(resolution, field, getattr(payload, field))
    if "engine_guidance" in payload.model_fields_set:   # omitted: unchanged
        resolution.engine_guidance = payload.engine_guidance
    resolution.updated_at = _now()


@router.get(
    "/{item_id}/resolutions",
    response_model=list[item_schemas.ResolutionOut],
    summary="List an item's resolutions",
    operation_id="list_item_resolutions",
    responses={404: _ITEM_NOT_FOUND},
)
def list_resolutions(
    item_id: str,
    include_deleted: bool = Query(False, description="Include soft-deleted resolutions."),
    db: Session = Depends(get_db),
):
    _get_item(db, item_id, include_deleted=include_deleted)
    query = db.query(models.ItemResolution).filter(models.ItemResolution.item_id == item_id)
    if not include_deleted:
        query = query.filter(models.ItemResolution.deleted_at.is_(None))
    return [_resolution_out(db, r) for r in query.order_by(models.ItemResolution.id)]


@router.post(
    "/{item_id}/resolutions",
    response_model=item_schemas.ResolutionOut,
    status_code=201,
    summary="Add a resolution to an item",
    operation_id="create_item_resolution",
    responses={404: _ITEM_NOT_FOUND, 409: {"model": ErrorResponse, "description": "Duplicate id, name, or a second default."}},
)
def create_resolution(item_id: str, payload: item_schemas.ResolutionCreate, db: Session = Depends(get_db)):
    # TODO: gate behind an admin role once auth exists.
    _get_item(db, item_id)
    if db.get(models.ItemResolution, payload.id) is not None:
        raise error(409, f"Resolution '{payload.id}' already exists", code="DUPLICATE_ID")
    _check_name_unique(db, item_id, payload.id, payload.name)
    _check_default_unique(db, item_id, payload.id, payload.is_default)
    resolution = models.ItemResolution(id=payload.id, item_id=item_id)
    _apply_resolution_fields(resolution, payload)
    # Exactly one default per item: an item's first resolution is its default.
    if _live_default(db, item_id) is None and resolution.status == "active":
        resolution.is_default = True
    db.add(resolution)
    db.commit()
    db.refresh(resolution)
    return _resolution_out(db, resolution)


@router.put(
    "/{item_id}/resolutions/{resolution_id}",
    response_model=item_schemas.ResolutionOut,
    summary="Replace a resolution",
    operation_id="update_item_resolution",
    responses={404: {"model": ErrorResponse, "description": "No such item or resolution."}, 409: {"model": ErrorResponse, "description": "Duplicate name, or a second default."}},
)
def update_resolution(
    item_id: str, resolution_id: str, payload: item_schemas.ResolutionWrite, db: Session = Depends(get_db)
):
    # TODO: gate behind an admin role once auth exists.
    _get_item(db, item_id)
    resolution = db.get(models.ItemResolution, resolution_id)
    if resolution is None or resolution.item_id != item_id or resolution.deleted_at is not None:
        raise error(404, f"Resolution '{resolution_id}' not found on item '{item_id}'", code="NOT_FOUND")
    _check_name_unique(db, item_id, resolution_id, payload.name)
    _check_default_unique(db, item_id, resolution_id, payload.is_default)
    _check_default_stays(db, resolution, unset=not payload.is_default, deactivate=payload.status != "active", remove=False)
    _apply_resolution_fields(resolution, payload)
    db.commit()
    db.refresh(resolution)
    return _resolution_out(db, resolution)


def move_default(db: Session, item_id: str, resolution_id: str) -> None:
    """Makes `resolution_id` the item's only default, as one unit: every
    other live resolution is unset first, then the target is set. Two
    statements, because PostgreSQL checks a non-deferrable unique index row
    by row and setting first would collide with the old default. The caller
    commits once; if either statement fails the transaction rolls back and
    the old default stands. uq_item_resolutions_one_default guarantees at
    most one live default whatever happens."""
    (
        db.query(models.ItemResolution)
        .filter(
            models.ItemResolution.item_id == item_id,
            models.ItemResolution.id != resolution_id,
            models.ItemResolution.is_default.is_(True),
        )
        .update({"is_default": False, "updated_at": _now()}, synchronize_session=False)
    )
    db.flush()
    (
        db.query(models.ItemResolution)
        .filter(models.ItemResolution.id == resolution_id)
        .update({"is_default": True, "updated_at": _now()}, synchronize_session=False)
    )
    db.flush()


@router.post(
    "/{item_id}/resolutions/{resolution_id}/make-default",
    response_model=list[item_schemas.ResolutionOut],
    summary="Make a resolution the item's default, in one transaction",
    response_description="The item's live resolutions after the move.",
    operation_id="make_item_resolution_default",
    responses={
        404: {"model": ErrorResponse, "description": "No such item or live resolution."},
        409: {"model": ErrorResponse, "description": "The resolution is deprecated and cannot be the default."},
    },
)
def make_default(item_id: str, resolution_id: str, db: Session = Depends(get_db)):
    """The default is the presumptive choice for every engagement, so it
    moves atomically: the old default is unset and the new one set in the
    same transaction, or nothing changes. Replaces unsetting and setting
    with two PUTs, where a failure between them left the item with no
    default."""
    # TODO: gate behind an admin role once auth exists.
    _get_item(db, item_id)
    resolution = db.get(models.ItemResolution, resolution_id)
    if resolution is None or resolution.item_id != item_id or resolution.deleted_at is not None:
        raise error(404, f"Resolution '{resolution_id}' not found on item '{item_id}'", code="NOT_FOUND")
    if resolution.status != "active":
        raise error(409, f"Resolution '{resolution_id}' is {resolution.status} and cannot be the default", code="NOT_ACTIVE")

    move_default(db, item_id, resolution_id)
    db.commit()
    return [
        _resolution_out(db, r)
        for r in db.query(models.ItemResolution)
        .filter(models.ItemResolution.item_id == item_id, models.ItemResolution.deleted_at.is_(None))
        .order_by(models.ItemResolution.id)
    ]


@router.delete(
    "/{item_id}/resolutions/{resolution_id}",
    response_model=item_schemas.SoftDeleteResponse,
    summary="Soft-delete a resolution",
    operation_id="delete_item_resolution",
    responses={
        404: {"model": ErrorResponse, "description": "No such item or resolution."},
        409: {"model": ErrorResponse, "description": "A live engagement decision selects this resolution."},
    },
)
def delete_resolution(
    item_id: str,
    resolution_id: str,
    deleted_by: str | None = Query(None, description="Free-text identity performing the delete."),
    db: Session = Depends(get_db),
):
    # TODO: gate behind an admin role once auth exists.
    resolution = db.get(models.ItemResolution, resolution_id)
    if resolution is None or resolution.item_id != item_id or resolution.deleted_at is not None:
        raise error(404, f"Resolution '{resolution_id}' not found on item '{item_id}'", code="NOT_FOUND")
    live = _live_decision_count(db, resolution_id=resolution_id)
    if live:
        raise error(
            409,
            f"Resolution '{resolution_id}' is selected by {live} non-superseded engagement decision(s).",
            code="REFERENCED_BY_DECISIONS",
        )
    _check_default_stays(db, resolution, unset=False, deactivate=False, remove=True)
    resolution.deleted_at = _now()
    resolution.deleted_by = deleted_by
    db.commit()
    return item_schemas.SoftDeleteResponse(id=resolution.id, deleted_at=resolution.deleted_at)


@router.post(
    "/{item_id}/resolutions/{resolution_id}/restore",
    response_model=item_schemas.SoftDeleteResponse,
    summary="Restore a soft-deleted resolution",
    operation_id="restore_item_resolution",
    responses={
        404: {"model": ErrorResponse, "description": "No such item or resolution."},
        409: {"model": ErrorResponse, "description": "Restoring it would create a second default."},
    },
)
def restore_resolution(item_id: str, resolution_id: str, db: Session = Depends(get_db)):
    # TODO: gate behind an admin role once auth exists.
    resolution = db.get(models.ItemResolution, resolution_id)
    if resolution is None or resolution.item_id != item_id:
        raise error(404, f"Resolution '{resolution_id}' not found on item '{item_id}'", code="NOT_FOUND")
    _check_default_unique(db, item_id, resolution_id, resolution.is_default)
    if not resolution.is_default and resolution.status == "active" and _live_default(db, item_id) is None:
        resolution.is_default = True
    resolution.deleted_at = None
    resolution.deleted_by = None
    resolution.updated_at = _now()
    db.commit()
    return item_schemas.SoftDeleteResponse(id=resolution.id, deleted_at=None)
