"""Evaluating one catalog item's detection against one project —
28-ITEM-AND-CONVERSION-MODEL.md Part E.

Pure functions, no I/O: step 6 (app/steps/item_detection.py) loads the
signals and metadata, this module decides.

The condition semantics are the ones the old step 4 engine used, kept
unchanged because the grammar is (Part E "Grammar"): value operators,
`category`/`type`/`sourceType` filters, `minimumExtractionConfidence`, and
the quantitative operators checked against the whole filtered row set. What
is gone is everything that fed a score: there are no weights, no penalties,
and `none` is a plain exclusion. A detection either holds or it does not.

Signal rows are `fingerprint_signals` rows as dicts: `signal_category`,
`signal_type`, `value`, `source_type`, `source_path`, `occurrence_count`,
`extraction_confidence`, `evidence`, and `repository_level` (True for a
repository-level row). Repository-level rows count for every condition
(Part E "Repository-level signals are visible to every project") but never
locate an occurrence.
"""

import re

# Hard cap on evidence entries carried by one occurrence row. Each signal row
# already caps its own evidence at 20; an occurrence can merge several rows.
MAX_EVIDENCE_PER_OCCURRENCE = 50


# ---------- conditions ----------


def matches_value(matcher: dict | None, actual: str | None) -> bool:
    if matcher is None:
        return True
    if actual is None:
        return False
    if matcher.get("equals") is not None and actual != matcher["equals"]:
        return False
    if matcher.get("in") and actual not in matcher["in"]:
        return False
    if matcher.get("startsWith") and not actual.startswith(matcher["startsWith"]):
        return False
    if matcher.get("contains") and matcher["contains"] not in actual:
        return False
    if matcher.get("regex") and re.search(matcher["regex"], actual) is None:
        return False
    return True


def filter_rows(signal: dict, rows: list[dict]) -> list[dict]:
    """The rows one signal condition's row-level predicates accept."""
    out = []
    for row in rows:
        if signal.get("category") and row["signal_category"] != signal["category"]:
            continue
        if signal.get("type") and row["signal_type"] != signal["type"]:
            continue
        if signal.get("sourceType") and row["source_type"] != signal["sourceType"]:
            continue
        if not matches_value(signal.get("value"), row["value"]):
            continue
        minimum = signal.get("minimumExtractionConfidence")
        if minimum is not None and row["extraction_confidence"] < minimum:
            continue
        out.append(row)
    return out


def evaluate_signal_condition(condition: dict, signals_by_name: dict[str, list[dict]]) -> tuple[bool, list[dict]]:
    """(holds, the rows that satisfied it)."""
    signal = condition["signal"]
    rows = filter_rows(signal, signals_by_name.get(signal["name"], []))
    if not rows:
        return False, []

    occurrences = sum(r["occurrence_count"] for r in rows)
    distinct_values = len({r["value"] for r in rows if r["value"] is not None})
    distinct_files = len({r["source_path"] for r in rows if r["source_path"] is not None})

    # With no quantitative operator, one matching row is enough.
    if signal.get("minimumOccurrences") is not None and occurrences < signal["minimumOccurrences"]:
        return False, []
    if signal.get("maximumOccurrences") is not None and occurrences > signal["maximumOccurrences"]:
        return False, []
    if signal.get("minimumDistinctValues") is not None and distinct_values < signal["minimumDistinctValues"]:
        return False, []
    if signal.get("minimumDistinctSourceFiles") is not None and distinct_files < signal["minimumDistinctSourceFiles"]:
        return False, []
    return True, rows


_POSITIVE_METADATA_OPERATORS = ("equals", "in", "startsWith", "contains", "regex")


def evaluate_metadata_condition(condition: dict, metadata: dict) -> bool:
    """Against step 2/3 project fields (outputType, frameworkFamily,
    structuralType, ...). `notEquals`/`notIn` are exclusions and an absent
    value passes them; a positive operator on an absent value fails."""
    actual = metadata.get(condition["field"])
    if condition.get("notEquals") is not None and actual == condition["notEquals"]:
        return False
    if condition.get("notIn") and actual in condition["notIn"]:
        return False
    if actual is None:
        return not any(condition.get(op) is not None for op in _POSITIVE_METADATA_OPERATORS)
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


# ---------- the match ----------


def evaluate_match(match: dict, signals_by_name: dict[str, list[dict]], metadata: dict) -> tuple[bool, list[dict]]:
    """(item applies, the rule records that held). `all`, `any` (an empty
    group is no constraint), each `atLeast` group, `metadata` and `none` must
    all be satisfied."""
    held: list[dict] = []

    for condition in match.get("all", []):
        ok, rows = evaluate_signal_condition(condition, signals_by_name)
        if not ok:
            return False, []
        held.append(_record(condition, rows))

    any_group = match.get("any", [])
    if any_group:
        any_held = []
        for condition in any_group:
            ok, rows = evaluate_signal_condition(condition, signals_by_name)
            if ok:
                any_held.append(_record(condition, rows))
        if not any_held:
            return False, []
        held.extend(any_held)

    for group in match.get("atLeast", []):
        group_held = []
        for condition in group.get("of", []):
            ok, rows = evaluate_signal_condition(condition, signals_by_name)
            if ok:
                group_held.append(_record(condition, rows))
        if len(group_held) < group["count"]:
            return False, []
        held.extend(group_held)

    for condition in match.get("metadata", []):
        if not evaluate_metadata_condition(condition, metadata):
            return False, []
        held.append({"rule_id": condition["id"], "field": condition["field"], "actual": metadata.get(condition["field"])})

    for condition in match.get("none", []):
        ok, _rows = evaluate_signal_condition(condition, signals_by_name)
        if ok:
            return False, []

    return True, held


def _record(condition: dict, rows: list[dict]) -> dict:
    return {
        "rule_id": condition["id"],
        "signal_name": condition["signal"]["name"],
        "rows": rows,
    }


# ---------- occurrence projection ----------


def project_occurrences(detection: dict, signals_by_name: dict[str, list[dict]]) -> list[dict]:
    """Part E: the `occurrence_source` signal's evidence, one occurrence per
    distinct `source_path` (or per `source_path` and value). Only rows that
    satisfy a positive condition naming that signal count — a Serilog sink
    whose path is not a Windows path is not an occurrence of an item whose
    condition requires one. Repository-level rows never locate anything, and
    a row with no source path cannot be located.

    Returns [{file_path, value, evidence}], sorted, evidence in line order."""
    source = detection["occurrence_source"]
    name = source["signal"]
    by_value = source.get("group_by", "source_path") == "source_path_and_value"

    match = detection["match"]
    conditions = [c for c in [*match.get("all", []), *match.get("any", [])] if c["signal"]["name"] == name]
    for group in match.get("atLeast", []):
        conditions += [c for c in group.get("of", []) if c["signal"]["name"] == name]

    project_rows = [r for r in signals_by_name.get(name, []) if not r["repository_level"] and r["source_path"]]
    accepted: dict[int, dict] = {}
    for condition in conditions:
        for row in filter_rows(condition["signal"], project_rows):
            accepted[id(row)] = row

    groups: dict[tuple[str, str | None], list[dict]] = {}
    for row in accepted.values():
        key = (row["source_path"], row["value"] if by_value else None)
        groups.setdefault(key, []).append(row)

    occurrences = []
    for (file_path, value), rows in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        evidence = []
        for row in sorted(rows, key=lambda r: r["value"] or ""):
            for entry in row["evidence"] or []:
                evidence.append(_evidence_entry(name, row["value"], entry))
            if not row["evidence"]:
                evidence.append(_evidence_entry(name, row["value"], {}))
        evidence.sort(key=lambda e: (e["line_start"] is None, e["line_start"] or 0, e["value"] or ""))
        occurrences.append({"file_path": file_path, "value": value, "evidence": evidence[:MAX_EVIDENCE_PER_OCCURRENCE]})
    return occurrences


def _evidence_entry(signal_name: str, value: str | None, entry: dict) -> dict:
    """ConversionContext shape (Part O J1): snake_case, the signal and value
    alongside the span. matched_value only where step 3 recorded one."""
    out = {
        "signal_name": signal_name,
        "value": value,
        "line_start": entry.get("lineStart"),
        "line_end": entry.get("lineEnd"),
    }
    for source_key, key in (("declaringType", "declaring_type"), ("member", "member"), ("matchedValue", "matched_value")):
        if entry.get(source_key) is not None:
            out[key] = entry[source_key]
    return out


def application_evidence(held: list[dict]) -> list[dict]:
    """For an application-scope row: which rules held, and where the
    signals behind them were seen. Metadata rules carry the field instead."""
    out = []
    for record in held:
        if "field" in record:
            out.append({"rule_id": record["rule_id"], "field": record["field"], "actual": record["actual"]})
            continue
        for row in sorted(record["rows"], key=lambda r: (r["source_path"] or "", r["value"] or "")):
            out.append({
                "rule_id": record["rule_id"],
                "signal_name": record["signal_name"],
                "source_path": row["source_path"],
                "value": row["value"],
                "repository_level": row["repository_level"],
            })
    return out[:MAX_EVIDENCE_PER_OCCURRENCE]
