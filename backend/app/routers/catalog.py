import datetime
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_db

router = APIRouter(prefix="/api/catalog", tags=["catalog"])

CATALOG_VERSION = "1.0"

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
    "forcing_factor",
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


@router.get("/export")
def export_catalog(
    include_engagements: bool = Query(False),
    include_timestamps: bool = Query(False),
    db: Session = Depends(get_db),
):
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

    pattern_payload = []
    for pattern in patterns:
        entry = _serialize(pattern, _PATTERN_FIELDS, include_timestamps)
        entry["target_state_options"] = [
            _serialize(option, _TARGET_STATE_FIELDS, include_timestamps)
            for option in options_by_pattern.get(pattern.id, [])
        ]
        pattern_payload.append(entry)

    engagement_payload: list[dict] = []
    decision_payload: list[dict] = []
    if include_engagements:
        engagements = (
            db.query(models.Engagement)
            .filter(models.Engagement.deleted_at.is_(None))
            .order_by(models.Engagement.id)
            .all()
        )
        engagement_payload = [
            _serialize(e, _ENGAGEMENT_FIELDS, include_timestamps) for e in engagements
        ]

        decisions = (
            db.query(models.DecisionRecord)
            .filter(models.DecisionRecord.deleted_at.is_(None))
            .order_by(models.DecisionRecord.id)
            .all()
        )
        decision_payload = [
            _serialize(d, _DECISION_FIELDS, include_timestamps) for d in decisions
        ]

    export = {
        "catalog_version": CATALOG_VERSION,
        "exported_at": _iso_utc(datetime.datetime.now(datetime.timezone.utc)),
        "patterns": pattern_payload,
        "engagements": engagement_payload,
        "decision_records": decision_payload,
    }

    body = json.dumps(export, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    return Response(content=body, media_type="application/json")


@router.post("/import", response_model=schemas.CatalogImportResult)
def import_catalog(
    payload: schemas.CatalogExport,
    mode: str = Query("merge", pattern="^(merge|replace)$"),
    confirm: bool = Query(False),
    db: Session = Depends(get_db),
):
    if mode == "replace" and not confirm:
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "field": "confirm",
                    "message": "mode=replace is destructive; pass ?confirm=true to proceed.",
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
        decision.forcing_factor = decision_data.get("forcing_factor")
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
