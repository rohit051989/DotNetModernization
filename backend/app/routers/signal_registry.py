"""Extractors, signal readiness and coverage —
28-ITEM-AND-CONVERSION-MODEL.md Parts C and H.

Every write here ends the same way: enforce the claim rule (a registered
signal no extractor claims is a hard error), then recompute readiness and
return what moved. That is how an item promotes with no edit to the item:
flip its blocking signal's extractor to `implemented` and the response's
`propagation.items_changed` lists it.
"""

from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.items import readiness, registry
from app.items import schemas as item_schemas
from app.items.detection import referenced_signal_names
from app.seed.seed_data import _load

router = APIRouter(prefix="/api/catalog", tags=["Item Catalog"])

_UNCLAIMED = {"model": ErrorResponse, "description": "The write would leave a registered signal unclaimed by any extractor."}
_NO_EXTRACTOR = "(none declared)"


def _live_items(db: Session) -> list[models.CatalogItem]:
    """Items that count for coverage: not soft-deleted, not deprecated."""
    return (
        db.query(models.CatalogItem)
        .filter(models.CatalogItem.deleted_at.is_(None), models.CatalogItem.status == "active")
        .order_by(models.CatalogItem.id)
        .all()
    )


# ---------- extractors ----------


@router.get(
    "/extractors",
    response_model=list[item_schemas.ExtractorOut],
    summary="List extractor declarations",
    operation_id="list_extractors",
)
def list_extractors(db: Session = Depends(get_db)):
    return db.query(models.Extractor).order_by(models.Extractor.name).all()


@router.put(
    "/extractors/{name}",
    response_model=item_schemas.ExtractorWriteResult,
    summary="Declare or update an extractor",
    response_description="The declaration, plus every signal and item whose readiness it changed.",
    operation_id="upsert_extractor",
    responses={422: _UNCLAIMED},
)
def upsert_extractor(name: str, payload: item_schemas.ExtractorDeclaration, db: Session = Depends(get_db)):
    """
    Setting `status: implemented` makes every registered signal this
    extractor declares `ready`, and promotes every item whose last blocking
    signal that was. Setting it back to `planned` demotes them the same way.

    Moving a name from `planned_emits` to `emits` on an implemented
    extractor is the other promotion path: the extractor already shipped
    and now emits this signal too.

    Rejected with 422 if the declaration drops a registered signal that
    expects this extractor from both lists — that signal would be unclaimed.
    """
    # TODO: gate behind an admin role once auth exists.
    extractor, created = registry.upsert_extractor(db, {"name": name, **payload.model_dump()})
    readiness.assert_all_signals_claimed(db)
    propagation = readiness.refresh_readiness(db, touched_signals={*extractor.emits, *extractor.planned_emits})
    db.commit()
    db.refresh(extractor)
    return item_schemas.ExtractorWriteResult(extractor=extractor, created=created, propagation=propagation)


# ---------- signals ----------


@router.get(
    "/signals",
    response_model=list[item_schemas.SignalOut],
    summary="List registered signals with readiness",
    operation_id="list_signals",
)
def list_signals(
    state: item_schemas.ReadinessState | None = Query(None, description="Filter by computed state."),
    db: Session = Depends(get_db),
):
    query = db.query(models.SignalRegistryEntry)
    if state is not None:
        query = query.filter(models.SignalRegistryEntry.state == state)
    return query.order_by(models.SignalRegistryEntry.name).all()


@router.get(
    "/signals/{name}",
    response_model=item_schemas.SignalOut,
    summary="Get one registered signal",
    operation_id="get_signal",
    responses={404: {"model": ErrorResponse, "description": "No signal is registered with this name."}},
)
def get_signal(name: str, db: Session = Depends(get_db)):
    signal = db.get(models.SignalRegistryEntry, name)
    if signal is None:
        raise error(404, f"Signal '{name}' is not registered", code="NOT_FOUND")
    return signal


@router.post(
    "/signals",
    response_model=item_schemas.SignalWriteResult,
    status_code=201,
    summary="Register a signal ahead of its registry file",
    operation_id="register_signal",
    responses={409: {"model": ErrorResponse, "description": "The signal is already registered."}, 422: _UNCLAIMED},
)
def register_signal(payload: item_schemas.SignalRegistration, db: Session = Depends(get_db)):
    """
    For a signal whose extraction code is not built yet. Declare it first:
    in `emits` of a `planned` extractor, or in `planned_emits` of an
    implemented one (`PUT /api/catalog/extractors/{name}`). Registering a
    signal its extractor does not declare is rejected. The signal then stays
    `not_ready` until it is in `emits` of an implemented extractor.

    Signals shipped by step 3 arrive through `POST /api/catalog/signals/sync`
    instead.
    """
    # TODO: gate behind an admin role once auth exists.
    if db.get(models.SignalRegistryEntry, payload.name) is not None:
        raise error(409, f"Signal '{payload.name}' is already registered", code="ALREADY_REGISTERED")
    readiness.assert_claimed(db, [(payload.name, payload.extractor)])
    signal, created = registry.upsert_signal(
        db, payload.model_dump(exclude={"signal_introduced_in_version"}), payload.signal_introduced_in_version
    )
    propagation = readiness.refresh_readiness(db, touched_signals={payload.name})
    db.commit()
    db.refresh(signal)
    return item_schemas.SignalWriteResult(signal=signal, created=created, propagation=propagation)


@router.post(
    "/signals/sync",
    response_model=item_schemas.RegistrySyncResult,
    summary="Resync signals from step 3's registry files",
    operation_id="sync_signal_registry",
    responses={422: _UNCLAIMED},
)
def sync_signal_registry(db: Session = Depends(get_db)):
    """
    Reloads backend/app/seed/data/extractors.yaml, the highest-versioned
    signal-registry-*.json and anticipated_signals.yaml, recomputing
    readiness. The same operation
    `python -m app.seed` runs. Fails without writing if any registry signal
    is not declared by its extractor.
    """
    # TODO: gate behind an admin role once auth exists.
    result = registry.sync_from_registry_files(
        db, _load("extractors.yaml")["extractors"], _load("anticipated_signals.yaml")["signals"]
    )
    db.commit()
    return result


# ---------- coverage (Part H) ----------


@router.get(
    "/item-coverage",
    response_model=item_schemas.ItemCoverage,
    summary="Items not ready, with blocking signals by extractor",
    operation_id="get_item_coverage",
)
def item_coverage(db: Session = Depends(get_db)):
    """Active items only. Soft-deleted and deprecated items are not
    evaluated by detection, so they are not coverage gaps."""
    items = _live_items(db)
    entries = []
    for item in items:
        if item.state == "ready":
            continue
        reason = item.state_reason or {}
        grouped: dict[str, list[str]] = defaultdict(list)
        for blocking in reason.get("blocking_signals", []):
            grouped[blocking.get("expected_extractor") or _NO_EXTRACTOR].append(blocking["signal"])
        entries.append(
            item_schemas.ItemCoverageEntry(
                item_id=item.id,
                name=item.name,
                scope=item.scope,
                reason_code=reason.get("reason_code", "signal_mapping_pending"),
                blocking_by_extractor={key: sorted(value) for key, value in sorted(grouped.items())},
            )
        )
    return item_schemas.ItemCoverage(
        ready_count=sum(1 for i in items if i.state == "ready"),
        not_ready_count=len(entries),
        not_ready=entries,
    )


@router.get(
    "/signal-coverage",
    response_model=item_schemas.SignalCoverage,
    summary="Ready signals no active item references",
    operation_id="get_signal_coverage",
)
def signal_coverage(db: Session = Depends(get_db)):
    referenced: set[str] = set()
    for item in _live_items(db):
        referenced |= referenced_signal_names(item.detection)
    ready = (
        db.query(models.SignalRegistryEntry)
        .filter(models.SignalRegistryEntry.state == "ready")
        .order_by(models.SignalRegistryEntry.name)
        .all()
    )
    return item_schemas.SignalCoverage(
        ready_signal_count=len(ready),
        referenced_ready_count=sum(1 for s in ready if s.name in referenced),
        unreferenced=[
            item_schemas.UnreferencedSignal(name=s.name, category=s.category, expected_extractor=s.expected_extractor)
            for s in ready
            if s.name not in referenced
        ],
    )


@router.get(
    "/extractor-backlog",
    response_model=item_schemas.ExtractorBacklog,
    summary="Extractor build order, by items each would unblock",
    operation_id="get_extractor_backlog",
)
def extractor_backlog(db: Session = Depends(get_db)):
    """
    Groups every active item's blocking signals by expected extractor.
    `items_unblocked` counts only items for which this extractor is the
    sole remaining blocker — building it alone makes them ready.
    `items_blocked` counts every item it contributes to.
    """
    extractors = {e.name: e for e in db.query(models.Extractor).all()}
    signals: dict[str | None, set[str]] = defaultdict(set)
    blocked: dict[str | None, set[str]] = defaultdict(set)
    unblocked: dict[str | None, set[str]] = defaultdict(set)

    for item in _live_items(db):
        if item.state == "ready" or not item.state_reason:
            continue
        per_item_extractors = set()
        for blocking in item.state_reason.get("blocking_signals", []):
            key = blocking.get("expected_extractor")
            signals[key].add(blocking["signal"])
            blocked[key].add(item.id)
            per_item_extractors.add(key)
        if len(per_item_extractors) == 1:
            unblocked[per_item_extractors.pop()].add(item.id)

    entries = [
        item_schemas.ExtractorBacklogEntry(
            expected_extractor=key,
            extractor_status=extractors[key].status if key in extractors else None,
            signals=sorted(signals[key]),
            items_blocked=sorted(blocked[key]),
            items_unblocked=sorted(unblocked[key]),
        )
        for key in signals
    ]
    entries.sort(key=lambda e: (-len(e.items_unblocked), -len(e.items_blocked), e.expected_extractor or "~"))
    return item_schemas.ExtractorBacklog(entries=entries)
