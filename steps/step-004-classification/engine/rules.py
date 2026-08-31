"""Rule evaluation over one project's signal index — Part C operators, Part E
match-score steps 1-5 (the pass/fail half, before scoring). Pure functions,
no I/O, so this is what --corpus mode exercises directly.
"""

import re


def _matches_value(matcher: dict | None, actual_value: str | None) -> bool:
    if matcher is None:
        return True
    if actual_value is None:
        return False
    if matcher.get("equals") is not None and actual_value != matcher["equals"]:
        return False
    if matcher.get("in") and actual_value not in matcher["in"]:
        return False
    if matcher.get("startsWith") and not actual_value.startswith(matcher["startsWith"]):
        return False
    if matcher.get("contains") and matcher["contains"] not in actual_value:
        return False
    if matcher.get("regex") and re.search(matcher["regex"], actual_value) is None:
        return False
    return True


def evaluate_signal_condition(condition: dict, signals_by_name: dict[str, list[dict]]) -> tuple[bool, list[dict]]:
    """Returns (satisfied, evidence_rows). `signals_by_name` maps a signal
    name to its aggregated fingerprint_signals rows for one project (each row:
    value, occurrence_count, extraction_confidence, source_path, category,
    type, source_type). A condition may match zero, one, or many rows —
    quantitative operators are checked against the whole filtered set."""
    sig = condition["signal"]
    rows = signals_by_name.get(sig["name"], [])

    filtered = []
    for row in rows:
        if sig.get("category") and row["signal_category"] != sig["category"]:
            continue
        if sig.get("type") and row["signal_type"] != sig["type"]:
            continue
        if sig.get("sourceType") and row["source_type"] != sig["sourceType"]:
            continue
        if not _matches_value(sig.get("value"), row["value"]):
            continue
        min_conf = sig.get("minimumExtractionConfidence")
        if min_conf is not None and row["extraction_confidence"] < min_conf:
            continue
        filtered.append(row)

    if not filtered:
        return False, []

    total_occurrences = sum(r["occurrence_count"] for r in filtered)
    distinct_values = len({r["value"] for r in filtered if r["value"] is not None})
    distinct_source_files = len({r["source_path"] for r in filtered if r["source_path"] is not None})

    if sig.get("minimumOccurrences") is not None and total_occurrences < sig["minimumOccurrences"]:
        return False, []
    if sig.get("maximumOccurrences") is not None and total_occurrences > sig["maximumOccurrences"]:
        return False, []
    if sig.get("minimumDistinctValues") is not None and distinct_values < sig["minimumDistinctValues"]:
        return False, []
    if sig.get("minimumDistinctSourceFiles") is not None and distinct_source_files < sig["minimumDistinctSourceFiles"]:
        return False, []

    return True, filtered


def evaluate_metadata_condition(condition: dict, project_metadata: dict) -> bool:
    """Part C 'Metadata conditions' — against step 2/3 project fields
    (outputType, projectFormat, frameworkFamily, frameworkVersion,
    projectSdk, structuralType, extension, fingerprintStatus), never signals."""
    actual = project_metadata.get(condition["field"])
    if actual is None:
        return False
    if condition.get("equals") is not None and actual != condition["equals"]:
        return False
    if condition.get("in") and actual not in condition["in"]:
        return False
    if condition.get("startsWith") and not str(actual).startswith(condition["startsWith"]):
        return False
    if condition.get("contains") and condition["contains"] not in str(actual):
        return False
    if condition.get("regex") and re.search(condition["regex"], str(actual)) is None:
        return False
    return True


def _rule_record(condition: dict, rows: list[dict], weight: float | None = None) -> dict:
    record = {
        "rule_id": condition["id"],
        "signal_name": condition["signal"]["name"],
        "actual_occurrences": sum(r["occurrence_count"] for r in rows),
        "required_occurrences": condition["signal"].get("minimumOccurrences"),
        "evidence": [
            {
                "source_path": r["source_path"],
                "value": r["value"],
                "extraction_confidence": r["extraction_confidence"],
            }
            for r in rows[:5]
        ],
    }
    if weight is not None:
        record["weight"] = weight
    return record


class RuleGroupOutcome:
    """Result of evaluating one pattern's `detection_rules` against a
    project — everything Part E steps 1-5 need before scoring, plus the
    bookkeeping §20 explainability wants."""

    def __init__(self):
        self.disqualified = False
        self.disqualifying_group: str | None = None
        self.matched_rules: list[dict] = []
        self.failed_rules: list[dict] = []
        self.negative_triggered: list[dict] = []
        self.supporting_matched: list[dict] = []
        self.penalties: float = 0.0
        self.matched_signal_rows: list[dict] = []  # for extraction_factor


def evaluate_ruleset(ruleset: dict, signals_by_name: dict, project_metadata: dict) -> RuleGroupOutcome:
    outcome = RuleGroupOutcome()

    # 1. all — every condition must match.
    for cond in ruleset.get("all", []):
        ok, rows = evaluate_signal_condition(cond, signals_by_name)
        record = _rule_record(cond, rows)
        if ok:
            outcome.matched_rules.append(record)
            outcome.matched_signal_rows.extend(rows)
        else:
            outcome.failed_rules.append(record)
            outcome.disqualified = True
            outcome.disqualifying_group = "all"
            return outcome

    # 2. any — at least one condition must match. Empty group is no constraint.
    any_group = ruleset.get("any", [])
    if any_group:
        any_matched, any_failed = [], []
        for cond in any_group:
            ok, rows = evaluate_signal_condition(cond, signals_by_name)
            record = _rule_record(cond, rows)
            if ok:
                any_matched.append(record)
                outcome.matched_signal_rows.extend(rows)
            else:
                any_failed.append(record)
        if not any_matched:
            outcome.matched_rules.extend(any_matched)
            outcome.failed_rules.extend(any_failed)
            outcome.disqualified = True
            outcome.disqualifying_group = "any"
            return outcome
        outcome.matched_rules.extend(any_matched)
        outcome.failed_rules.extend(any_failed)

    # 3. atLeast — each group needs `count` of its `of` conditions to match.
    for group in ruleset.get("atLeast", []):
        group_matched, group_failed = [], []
        for cond in group.get("of", []):
            ok, rows = evaluate_signal_condition(cond, signals_by_name)
            record = _rule_record(cond, rows)
            if ok:
                group_matched.append(record)
                outcome.matched_signal_rows.extend(rows)
            else:
                group_failed.append(record)
        outcome.matched_rules.extend(group_matched)
        outcome.failed_rules.extend(group_failed)
        if len(group_matched) < group["count"]:
            outcome.disqualified = True
            outcome.disqualifying_group = "atLeast"
            return outcome

    # 4. metadata — every condition must pass.
    for cond in ruleset.get("metadata", []):
        ok = evaluate_metadata_condition(cond, project_metadata)
        record = {"rule_id": cond["id"], "field": cond["field"], "actual": project_metadata.get(cond["field"])}
        if ok:
            outcome.matched_rules.append(record)
        else:
            outcome.failed_rules.append(record)
            outcome.disqualified = True
            outcome.disqualifying_group = "metadata"
            return outcome

    # 5. none — disqualify fires -> NOT MATCHED; penalty fires -> accumulate.
    for cond in ruleset.get("none", []):
        ok, rows = evaluate_signal_condition(cond, signals_by_name)
        if not ok:
            continue
        record = _rule_record(cond, rows)
        outcome.negative_triggered.append(record)
        if cond.get("disqualify"):
            outcome.disqualified = True
            outcome.disqualifying_group = "none-disqualify"
            return outcome
        if cond.get("penalty"):
            outcome.penalties += cond["penalty"]

    # supporting — collected here so the caller can score in one place
    # (Part E steps 6-8 are pure arithmetic over what's gathered so far).
    for cond in ruleset.get("supporting", []):
        ok, rows = evaluate_signal_condition(cond, signals_by_name)
        if ok:
            outcome.supporting_matched.append(_rule_record(cond, rows, weight=cond["weight"]))
            outcome.matched_signal_rows.extend(rows)

    return outcome


def score_outcome(outcome: RuleGroupOutcome) -> int:
    """Part E steps 6-8. Step 9 (matched if >= thresholds.minimumScore) is
    the caller's job since it needs the pattern's own thresholds."""
    if outcome.disqualified:
        return 0
    base_score = 50
    supporting_score = min(50, sum(r["weight"] for r in outcome.supporting_matched))
    return max(0, min(100, round(base_score + supporting_score - outcome.penalties)))
