import datetime
import json
import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app import catalog_rules, models, schemas
from app.db import get_db
from app.errors import ErrorResponse, errors

router = APIRouter(prefix="/api/catalog", tags=["Catalog"])

CATALOG_VERSION = "2.0"

_PATTERN_FIELDS = [
    "id",
    "name",
    "summary",
    "description",
    "legacy_stack",
    "category",
    "detection_rules",
    "typical_indicators",
    "known_risks",
    "status",
    "version",
    "classification_role",
    "classification_family",
    "classification_value",
    "scope",
    "priority",
    "compatible_with",
    "conflicts_with",
    "anchor_signals",
    "eligibility",
    "analysis_requirements",
    "thresholds",
    "rules_status",
    "required_signals_pending",
]
_TARGET_STATE_FIELDS = [
    "id",
    "pattern_id",
    "name",
    "summary",
    "target_stack",
    "consumer_impact",
    "effort",
    "linux_compatible",
    "container_ready",
    "is_lift_and_shift",
    "is_recommended",
    "engine_support",
    "playbook_md",
    "prerequisites",
    "known_limitations",
    "status",
    "version",
]
_ENGAGEMENT_FIELDS = [
    "id",
    "client_name",
    "description",
    "target_platform",
    "default_posture",
    "status",
]
_DECISION_FIELDS = [
    "id",
    "engagement_id",
    "pattern_id",
    "selected_target_state_id",
    "candidates_considered",
    "evaluation_notes",
    "forcing_perspective",
    "forcing_rationale",
    "rationale",
    "approver_name",
    "approver_role",
    "decision_date",
    "status",
]
_TIMESTAMP_FIELDS = ["created_at", "updated_at"]


def _iso_utc(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _serialize(obj, fields: list[str], include_timestamps: bool) -> dict:
    data = {}
    for field in fields:
        value = getattr(obj, field)
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif isinstance(value, datetime.date):
            value = value.isoformat()
        data[field] = value
    if include_timestamps:
        for field in _TIMESTAMP_FIELDS:
            data[field] = _iso_utc(getattr(obj, field))
    return data


@router.get(
    "/export",
    summary="Export the catalog as deterministic JSON",
    response_description="A byte-identical-for-identical-data JSON document, suitable for committing to git.",
    operation_id="export_catalog",
    responses={422: {"model": ErrorResponse, "description": "scope=engagement without a valid engagement_id."}},
)
def export_catalog(
    scope: str = Query(
        "master",
        pattern="^(master|engagement)$",
        description="'master' (default) exports only patterns and target state options — client-agnostic, no overlay or decisions, regardless of include_engagements. 'engagement' additionally merges one engagement's overlay and decisions.",
    ),
    engagement_id: str | None = Query(
        None, description="Required when scope=engagement; ignored otherwise."
    ),
    include_engagements: bool = Query(
        False, description="Also include the engagements/decision_records arrays. Only takes effect with scope=engagement."
    ),
    include_timestamps: bool = Query(
        False, description="Include created_at/updated_at. Excluded by default to keep diffs quiet."
    ),
    db: Session = Depends(get_db),
):
    """
    **The export is deterministic**: keys sorted alphabetically at every
    level, `patterns`/`target_state_options` sorted by id, 2-space indent,
    trailing newline, timestamps as ISO-8601 UTC. Soft-deleted records are
    excluded unconditionally, with no override — a committed catalog file
    should never contain something that was removed, even for inspection.
    This is what lets the catalog be committed to git and reviewed as a pull
    request rather than living only as rows in a database.
    """
    if scope == "engagement":
        if not engagement_id:
            raise errors(
                422,
                [
                    {
                        "field": "engagement_id",
                        "message": "engagement_id is required when scope=engagement.",
                        "code": "MISSING_ENGAGEMENT_ID",
                    }
                ],
            )
        if db.get(models.Engagement, engagement_id) is None:
            raise errors(
                422,
                [
                    {
                        "field": "engagement_id",
                        "message": f"Engagement '{engagement_id}' does not exist.",
                        "code": "ENGAGEMENT_NOT_FOUND",
                    }
                ],
            )

    # Soft-deleted records are excluded unconditionally — a committed catalog file
    # should never contain something that was removed, even for inspection.
    patterns = (
        db.query(models.Pattern)
        .filter(models.Pattern.deleted_at.is_(None))
        .order_by(models.Pattern.id)
        .all()
    )

    options_by_pattern: dict[str, list[models.TargetStateOption]] = {}
    target_state_query = (
        db.query(models.TargetStateOption)
        .filter(models.TargetStateOption.deleted_at.is_(None))
        .order_by(models.TargetStateOption.id)
    )
    for option in target_state_query.all():
        options_by_pattern.setdefault(option.pattern_id, []).append(option)

    # scope=engagement merges this one engagement's overlay onto each pattern
    # entry. scope=master (the default) never does this, regardless of
    # include_engagements — the master export must stay client-agnostic.
    overlays_by_pattern: dict[str, models.EngagementPattern] = {}
    if scope == "engagement":
        overlays_by_pattern = {
            overlay.pattern_id: overlay
            for overlay in db.query(models.EngagementPattern)
            .filter(models.EngagementPattern.engagement_id == engagement_id)
            .all()
        }

    pattern_payload = []
    for pattern in patterns:
        entry = _serialize(pattern, _PATTERN_FIELDS, include_timestamps)
        entry["target_state_options"] = [
            _serialize(option, _TARGET_STATE_FIELDS, include_timestamps)
            for option in options_by_pattern.get(pattern.id, [])
        ]
        if scope == "engagement":
            overlay = overlays_by_pattern.get(pattern.id)
            entry["scope_status"] = overlay.scope_status if overlay else "active"
            entry["deferred_reason"] = overlay.deferred_reason if overlay else None
        pattern_payload.append(entry)

    # The top-level engagements/decision_records arrays remain opt-in via
    # include_engagements, but only ever populated in scope=engagement, and then
    # only for that one engagement — never the whole roster.
    engagement_payload: list[dict] = []
    decision_payload: list[dict] = []
    if scope == "engagement" and include_engagements:
        engagements = (
            db.query(models.Engagement)
            .filter(models.Engagement.deleted_at.is_(None), models.Engagement.id == engagement_id)
            .order_by(models.Engagement.id)
            .all()
        )
        engagement_payload = [
            _serialize(e, _ENGAGEMENT_FIELDS, include_timestamps) for e in engagements
        ]

        decisions = (
            db.query(models.DecisionRecord)
            .filter(
                models.DecisionRecord.deleted_at.is_(None),
                models.DecisionRecord.engagement_id == engagement_id,
            )
            .order_by(models.DecisionRecord.id)
            .all()
        )
        decision_payload = [
            _serialize(d, _DECISION_FIELDS, include_timestamps) for d in decisions
        ]

    export = {
        "catalog_version": CATALOG_VERSION,
        "catalog_revision": catalog_rules.current_catalog_revision(db),
        "exported_at": _iso_utc(datetime.datetime.now(datetime.timezone.utc)),
        "patterns": pattern_payload,
        "engagements": engagement_payload,
        "decision_records": decision_payload,
    }

    body = json.dumps(export, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    return Response(content=body, media_type="application/json")


@router.get(
    "/signal-registry",
    response_model=schemas.SignalRegistryOut,
    summary="Get the active step 3 signal registry",
    response_description="Every registered signal with its category, type, description and extractor — what the rule builder's signal selects are populated from.",
    operation_id="get_signal_registry",
)
def get_signal_registry():
    """The active registry is the highest-versioned
    steps/step-003-fingerprinting/schemas/signal-registry-*.json file on
    disk. `weak_anchor: true` flags a signal §7 says must not be a
    pattern's only anchor."""
    return schemas.SignalRegistryOut(
        registry_version=catalog_rules.registry_version(),
        signals=catalog_rules.registered_signals_full(),
    )


@router.get(
    "/pending-signals",
    response_model=list[schemas.PendingSignalPromotion],
    summary="Report which awaiting_signals patterns are now promotable",
    response_description="Every non-deleted 'awaiting_signals' pattern, with its promotion status against the currently active signal registry.",
    operation_id="get_pending_signal_promotions",
)
def get_pending_signal_promotions(db: Session = Depends(get_db)):
    """
    Re-checks every `rules_status: 'awaiting_signals'` pattern's
    `required_signals_pending` against the active step 3 signal registry.
    `promotable: true` means every *blocking* pending signal is now
    registered — promoting the pattern to `active` (via `PUT
    /api/patterns/{id}`) stays a human action; this endpoint only reports
    readiness (24-STEP-004-CLASSIFICATION.md Part B3).
    """
    return catalog_rules.pending_signal_promotions(db)


@router.post(
    "/import",
    response_model=schemas.CatalogImportResult,
    summary="Import a catalog export",
    response_description="Counts of records created and updated.",
    operation_id="import_catalog",
    responses={422: {"model": ErrorResponse, "description": "mode=replace without ?confirm=true."}},
)
def import_catalog(
    payload: schemas.CatalogExport,
    mode: str = Query(
        "merge",
        pattern="^(merge|replace)$",
        description="'merge' (default) upserts by id and leaves unlisted records untouched. 'replace' additionally deprecates every pattern/target state option not present in the payload.",
    ),
    confirm: bool = Query(
        False, description="Required (must be true) when mode=replace, since that mode is destructive."
    ),
    db: Session = Depends(get_db),
):
    """Upserts patterns, target state options, engagements, and decision
    records by id. `mode=replace` is destructive — every pattern and target
    state option not present in the payload is set to `status: 'deprecated'`
    (never hard-deleted; see CLAUDE.md's soft-delete convention)."""
    if mode == "replace" and not confirm:
        raise errors(
            422,
            [
                {
                    "field": "confirm",
                    "message": "mode=replace is destructive; pass ?confirm=true to proceed.",
                    "code": "CONFIRMATION_REQUIRED",
                }
            ],
        )

    result = {
        "patterns_created": 0,
        "patterns_updated": 0,
        "target_state_options_created": 0,
        "target_state_options_updated": 0,
        "engagements_created": 0,
        "engagements_updated": 0,
        "decision_records_created": 0,
        "decision_records_updated": 0,
    }

    seen_pattern_ids: set[str] = set()
    seen_target_state_ids: set[str] = set()

    for pattern_data in payload.patterns:
        pattern_id = pattern_data["id"]
        seen_pattern_ids.add(pattern_id)

        pattern = db.get(models.Pattern, pattern_id)
        if pattern is None:
            pattern = models.Pattern(id=pattern_id)
            db.add(pattern)
            result["patterns_created"] += 1
        else:
            result["patterns_updated"] += 1

        pattern.name = pattern_data["name"]
        pattern.summary = pattern_data["summary"]
        pattern.description = pattern_data.get("description")
        pattern.legacy_stack = pattern_data["legacy_stack"]
        pattern.category = pattern_data["category"]
        pattern.detection_rules = pattern_data["detection_rules"]
        pattern.typical_indicators = pattern_data.get("typical_indicators")
        pattern.known_risks = pattern_data.get("known_risks")
        pattern.status = pattern_data.get("status", "active")
        if "version" in pattern_data:
            pattern.version = pattern_data["version"]

        for option_data in pattern_data.get("target_state_options", []):
            option_id = option_data["id"]
            seen_target_state_ids.add(option_id)

            option = db.get(models.TargetStateOption, option_id)
            if option is None:
                option = models.TargetStateOption(id=option_id, pattern_id=pattern_id)
                db.add(option)
                result["target_state_options_created"] += 1
            else:
                result["target_state_options_updated"] += 1

            option.pattern_id = pattern_id
            option.name = option_data["name"]
            option.summary = option_data["summary"]
            option.target_stack = option_data["target_stack"]
            option.consumer_impact = option_data["consumer_impact"]
            option.effort = option_data["effort"]
            option.linux_compatible = option_data.get("linux_compatible", True)
            option.container_ready = option_data.get("container_ready", True)
            option.is_lift_and_shift = option_data.get("is_lift_and_shift", False)
            option.is_recommended = option_data.get("is_recommended", False)
            option.engine_support = option_data.get("engine_support")
            option.playbook_md = option_data.get("playbook_md")
            option.prerequisites = option_data.get("prerequisites")
            option.known_limitations = option_data.get("known_limitations")
            option.status = option_data.get("status", "active")
            if "version" in option_data:
                option.version = option_data["version"]

    for engagement_data in payload.engagements:
        engagement_id = engagement_data["id"]
        engagement = db.get(models.Engagement, engagement_id)
        if engagement is None:
            engagement = models.Engagement(id=engagement_id)
            db.add(engagement)
            result["engagements_created"] += 1
        else:
            result["engagements_updated"] += 1

        engagement.client_name = engagement_data["client_name"]
        engagement.description = engagement_data.get("description")
        engagement.target_platform = engagement_data.get("target_platform")
        engagement.default_posture = engagement_data.get("default_posture", "lift-and-shift")
        engagement.status = engagement_data.get("status", "active")

    for decision_data in payload.decision_records:
        decision_id = uuid.UUID(decision_data["id"])
        decision = db.get(models.DecisionRecord, decision_id)
        if decision is None:
            decision = models.DecisionRecord(id=decision_id)
            db.add(decision)
            result["decision_records_created"] += 1
        else:
            result["decision_records_updated"] += 1

        decision.engagement_id = decision_data["engagement_id"]
        decision.pattern_id = decision_data["pattern_id"]
        decision.selected_target_state_id = decision_data.get("selected_target_state_id")
        decision.candidates_considered = decision_data.get("candidates_considered")
        decision.evaluation_notes = decision_data.get("evaluation_notes")
        decision.forcing_perspective = decision_data.get("forcing_perspective")
        decision.forcing_rationale = decision_data.get("forcing_rationale")
        decision.rationale = decision_data.get("rationale")
        decision.approver_name = decision_data.get("approver_name")
        decision.approver_role = decision_data.get("approver_role")
        decision_date = decision_data.get("decision_date")
        decision.decision_date = (
            datetime.date.fromisoformat(decision_date) if decision_date else None
        )
        decision.status = decision_data.get("status", "parked")

    if mode == "replace":
        db.query(models.Pattern).filter(
            models.Pattern.id.notin_(seen_pattern_ids),
            models.Pattern.status != "deprecated",
        ).update({"status": "deprecated"}, synchronize_session=False)

        db.query(models.TargetStateOption).filter(
            models.TargetStateOption.id.notin_(seen_target_state_ids),
            models.TargetStateOption.status != "deprecated",
        ).update({"status": "deprecated"}, synchronize_session=False)

    db.commit()
    return result
