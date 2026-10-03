"""Catalog item detection grammar and write-time validation —
28-ITEM-AND-CONVERSION-MODEL.md Part E.

`match` decides whether an item applies; `occurrence_source` decides where.
The condition grammar is the existing signal-rules grammar (`all`, `any`,
`atLeast`, `none`, `metadata`) minus everything that fed a score: no
`supporting` group, no weights, and a `none` condition simply excludes (no
`disqualify` flag, no `penalty`). A condition either holds or it does not.

Nothing here decides readiness. An item may reference a signal that is not
registered yet; readiness.py then computes it `not_ready`, and a `not_ready`
item is never evaluated by detection. That is the whole mechanism behind
"detection may reference unregistered signals only while the item is
not_ready": there is no path by which such an item becomes ready.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.errors import errors
from app.schemas import AtLeastGroup, MetadataCondition, RuleCondition

ItemScope = Literal["application", "occurrence"]


class ItemMatch(BaseModel):
    """Whether the item applies. All groups optional; an absent or empty
    group imposes no constraint."""

    model_config = ConfigDict(extra="forbid")

    all: list[RuleCondition] = Field(default_factory=list, description="Every condition here must hold.")
    any: list[RuleCondition] = Field(default_factory=list, description="At least one condition here must hold.")
    atLeast: list[AtLeastGroup] = Field(
        default_factory=list, description="Each group requires at least `count` of its `of` conditions to hold."
    )
    none: list[RuleCondition] = Field(
        default_factory=list, description="No condition here may hold. Exclusion only; there is no score to penalise."
    )
    metadata: list[MetadataCondition] = Field(
        default_factory=list, description="Conditions against project metadata rather than signals."
    )


class OccurrenceSource(BaseModel):
    """Which signal's evidence defines the item's locations (Part E)."""

    model_config = ConfigDict(extra="forbid")

    signal: str = Field(description="A signal named in a positive `match` group whose evidence supplies file paths.")
    group_by: Literal["source_path", "source_path_and_value"] = Field(
        default="source_path",
        description="'source_path': one occurrence per distinct path. 'source_path_and_value': distinct values "
        "at the same path are separate occurrences.",
    )
    also: list[str] | None = Field(
        default=None,
        description="Further positive-match signals that locate occurrences the same way, for an item matched by "
        "`any` of several signals. A row at the same path and line as an occurrence already projected (from "
        "`signal`, then `also` in order) joins that occurrence rather than making a second one.",
    )


class ItemDetection(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "match": {"all": [{"id": "has-file-sink", "signal": {"name": "SERILOG_FILE_SINK_CONFIG"}}]},
                    "occurrence_source": {"signal": "SERILOG_FILE_SINK_CONFIG", "group_by": "source_path"},
                }
            ]
        },
    )

    match: ItemMatch = Field(default_factory=ItemMatch, description="Whether the item applies to a project.")
    occurrence_source: OccurrenceSource | None = Field(
        default=None,
        description="Required for occurrence scope, rejected for application scope.",
    )


# ---------- signal references ----------


def positive_signal_names(match: dict) -> set[str]:
    """Signals whose presence can make the item apply: `all`, `any` and
    `atLeast.of`. Only these can locate an occurrence."""
    names = {c["signal"]["name"] for c in match.get("all", [])}
    names |= {c["signal"]["name"] for c in match.get("any", [])}
    for group in match.get("atLeast", []):
        names |= {c["signal"]["name"] for c in group.get("of", [])}
    return names


def referenced_signal_names(detection: dict) -> set[str]:
    """Every signal the detection depends on, exclusions included — an item
    cannot honestly evaluate `none: [X]` without X's extractor either."""
    match = detection.get("match", {})
    names = positive_signal_names(match)
    names |= {c["signal"]["name"] for c in match.get("none", [])}
    source = detection.get("occurrence_source")
    if source:
        names.add(source["signal"])
        names.update((source.get("also") or []))
    return names


# ---------- rule ids ----------


def _assign_ids(conditions: list[dict], prefix: str) -> None:
    for index, condition in enumerate(conditions):
        if not condition.get("id"):
            condition["id"] = f"{prefix}[{index}]"


def _assign_positional_ids(match: dict) -> list[str]:
    """Backfills a positional id (e.g. 'all[0]') for any condition without
    one, as the pattern grammar does. Returns every id in order."""
    for group in ("all", "any", "none", "metadata"):
        _assign_ids(match.get(group, []), group)
    for index, group in enumerate(match.get("atLeast", [])):
        if not group.get("id"):
            group["id"] = f"atLeast[{index}]"
        _assign_ids(group.get("of", []), f"atLeast[{index}].of")

    ids = []
    for group in ("all", "any", "none", "metadata"):
        ids += [c["id"] for c in match.get(group, [])]
    for group in match.get("atLeast", []):
        ids.append(group["id"])
        ids += [c["id"] for c in group.get("of", [])]
    return ids


# ---------- validation ----------


def validate_detection(scope: str, detection: dict, registered: dict[str, str]) -> tuple[dict, list[str]]:
    """Parses and validates one item's detection for its scope. `registered`
    maps each registered signal name to its evidence_kind.

    Returns (normalised detection, warnings). Raises a 422 listing every
    problem found. Warnings never block the write."""
    try:
        parsed = ItemDetection.model_validate(detection)
    except ValidationError as exc:
        raise errors(
            422,
            [
                {
                    "field": "detection." + ".".join(str(part) for part in e["loc"]),
                    "message": e["msg"],
                    "code": "INVALID_DETECTION",
                }
                for e in exc.errors()
            ],
        ) from exc

    normalised = parsed.model_dump(by_alias=True, exclude_none=True)
    match = normalised["match"]
    problems: list[dict] = []
    warnings: list[str] = []

    ids = _assign_positional_ids(match)
    duplicates = sorted({rule_id for rule_id in ids if ids.count(rule_id) > 1})
    problems += [
        {
            "field": "detection.match",
            "message": f"Rule id '{rule_id}' is used more than once; ids must be unique within an item.",
            "code": "DUPLICATE_RULE_ID",
        }
        for rule_id in duplicates
    ]

    source = normalised.get("occurrence_source")
    if scope == "occurrence" and source is None:
        problems.append(
            {
                "field": "detection.occurrence_source",
                "message": "An occurrence-scope item must declare occurrence_source: which signal's evidence defines its locations.",
                "code": "OCCURRENCE_SOURCE_REQUIRED",
            }
        )
    if scope == "application" and source is not None:
        problems.append(
            {
                "field": "detection.occurrence_source",
                "message": "An application-scope item has no occurrence projection; the project is the unit. Remove occurrence_source.",
                "code": "OCCURRENCE_SOURCE_NOT_ALLOWED",
            }
        )
    for source_signal in ([source["signal"], *(source.get("also") or [])] if source is not None else []):
        if source_signal not in positive_signal_names(match):
            problems.append(
                {
                    "field": "detection.occurrence_source.signal",
                    "message": f"occurrence_source names '{source_signal}', which does not appear in match.all, "
                    "match.any or match.atLeast. The located signal must be one the match depends on.",
                    "code": "OCCURRENCE_SOURCE_NOT_IN_MATCH",
                }
            )
        elif registered.get(source_signal) == "NONE":
            problems.append(
                {
                    "field": "detection.occurrence_source.signal",
                    "message": f"Signal '{source_signal}' has evidence_kind NONE: its evidence carries no location to project.",
                    "code": "OCCURRENCE_SOURCE_HAS_NO_LOCATION",
                }
            )

    if problems:
        raise errors(422, problems)

    unregistered = sorted(referenced_signal_names(normalised) - registered.keys())
    if unregistered:
        warnings.append(
            "Not yet registered, so this item stays not_ready until they are: " + ", ".join(unregistered) + "."
        )
    return normalised, warnings
